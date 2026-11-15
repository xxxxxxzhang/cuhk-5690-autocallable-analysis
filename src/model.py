"""Generate risk-neutral correlated-GBM paths on contractual observation dates."""
import csv
from copy import deepcopy
from datetime import date
from math import exp, isfinite, sqrt
from random import Random
from statistics import median

import numpy as np
import yaml

from .payoff import ROOT


def load_model_inputs(path=ROOT / "config/model_inputs.yaml"):
    """Load the explicitly provisional Monte Carlo assumptions."""
    inputs = yaml.safe_load(path.read_text())
    if inputs.get("model") != "correlated_gbm":
        raise ValueError("Only model='correlated_gbm' is currently implemented")
    return inputs


def calibrate_historical(path, start, end, symbols):
    """Estimate annualized volatility and correlation from adjusted closes."""
    with path.open(newline="", encoding="utf-8") as source:
        rows = [
            row for row in csv.DictReader(source)
            if start <= row["date"] <= end
        ]
    rows.sort(key=lambda row: row["date"])
    if len(rows) < 3 or rows[-1]["date"] != end:
        raise ValueError("Calibration requires at least three prices through the end date")
    if len({row["date"] for row in rows}) != len(rows):
        raise ValueError("Calibration data contain duplicate dates")
    prices = np.array(
        [[float(row[symbol]) for symbol in symbols] for row in rows], dtype=float
    )
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("Calibration prices must be positive and finite")
    returns = np.diff(np.log(prices), axis=0)
    volatility = returns.std(axis=0, ddof=1) * np.sqrt(252.0)
    correlation = np.corrcoef(returns.T)
    return {
        "window_start": start,
        "window_end": end,
        "daily_returns": len(returns),
        "volatilities": dict(zip(symbols, volatility.tolist(), strict=True)),
        "correlation": {
            left: dict(zip(symbols, correlation[index].tolist(), strict=True))
            for index, left in enumerate(symbols)
        },
    }


def inputs_with_calibration(base_inputs, calibration):
    """Return a model-input copy using one historical calibration window."""
    inputs = deepcopy(base_inputs)
    inputs["volatilities"] = deepcopy(calibration["volatilities"])
    inputs["correlation"] = deepcopy(calibration["correlation"])
    return inputs


def _year_fraction(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.0


def _cholesky(correlation):
    """Return a lower Cholesky factor after validating a correlation matrix."""
    size = len(correlation)
    if size == 0 or any(len(row) != size for row in correlation):
        raise ValueError("Correlation matrix must be non-empty and square")
    for i in range(size):
        if abs(correlation[i][i] - 1.0) > 1e-10:
            raise ValueError("Correlation matrix diagonal must equal one")
        for j in range(size):
            value = correlation[i][j]
            if not isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError("Correlation entries must be finite and between -1 and 1")
            if abs(value - correlation[j][i]) > 1e-10:
                raise ValueError("Correlation matrix must be symmetric")

    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            residual = correlation[i][j] - sum(
                lower[i][k] * lower[j][k] for k in range(j)
            )
            if i == j:
                if residual <= 1e-12:
                    raise ValueError("Correlation matrix must be positive definite")
                lower[i][j] = sqrt(residual)
            else:
                lower[i][j] = residual / lower[j][j]
    return lower


def _validated_parameters(terms, inputs):
    symbols = list(terms["underlyings"])
    rate = float(inputs["risk_free_rate"])
    volatilities = [float(inputs["volatilities"][symbol]) for symbol in symbols]
    dividends = [float(inputs["dividend_yields"][symbol]) for symbol in symbols]
    correlation = [
        [float(inputs["correlation"][left][right]) for right in symbols]
        for left in symbols
    ]
    if not isfinite(rate):
        raise ValueError("Risk-free rate must be finite")
    if any(not isfinite(value) or value < 0 for value in volatilities):
        raise ValueError("Volatilities must be finite and non-negative")
    if any(not isfinite(value) for value in dividends):
        raise ValueError("Dividend yields must be finite")
    return symbols, rate, volatilities, dividends, _cholesky(correlation)


def simulate_paths(terms, inputs, *, n_paths=None, seed=None):
    """Simulate absolute prices for every contractual observation date.

    The process is risk-neutral correlated GBM.  Each returned item has exactly
    the structure expected by ``payoff.evaluate_note``:
    ``path[observation_date][symbol] = absolute_price``.
    """
    symbols, rate, volatilities, dividends, lower = _validated_parameters(terms, inputs)
    count = int(inputs["n_paths"] if n_paths is None else n_paths)
    random_seed = int(inputs["seed"] if seed is None else seed)
    if count <= 0:
        raise ValueError("n_paths must be positive")

    rng = Random(random_seed)
    observation_dates = [row[0] for row in terms["schedule"]]
    intervals = []
    previous = terms["pricing_date"]
    for observation in observation_dates:
        dt = _year_fraction(previous, observation)
        if dt <= 0:
            raise ValueError("Observation dates must follow the pricing date")
        intervals.append(dt)
        previous = observation

    simulated = []
    for _ in range(count):
        levels = [float(terms["underlyings"][symbol]["initial"]) for symbol in symbols]
        path = {}
        for observation, dt in zip(observation_dates, intervals, strict=True):
            independent = [rng.gauss(0.0, 1.0) for _ in symbols]
            shocks = [
                sum(lower[i][j] * independent[j] for j in range(i + 1))
                for i in range(len(symbols))
            ]
            for i, _symbol in enumerate(symbols):
                sigma = volatilities[i]
                drift = (rate - dividends[i] - 0.5 * sigma * sigma) * dt
                diffusion = sigma * sqrt(dt) * shocks[i]
                levels[i] *= exp(drift + diffusion)
            path[observation] = dict(zip(symbols, levels, strict=True))
        simulated.append(path)
    return simulated


def standard_normal_shocks(terms, inputs, *, n_paths=None, seed=None):
    """Generate reusable independent shocks for common-random-number scenarios."""
    count = int(inputs["n_paths"] if n_paths is None else n_paths)
    random_seed = int(inputs["seed"] if seed is None else seed)
    if count <= 0:
        raise ValueError("n_paths must be positive")
    return np.random.default_rng(random_seed).standard_normal(
        (count, len(terms["schedule"]), len(terms["underlyings"]))
    )


def simulate_price_array(terms, inputs, *, shocks=None, n_paths=None, seed=None):
    """Vectorized correlated-GBM simulation on contractual observation dates."""
    symbols, rate, volatilities, dividends, lower = _validated_parameters(terms, inputs)
    if shocks is None:
        shocks = standard_normal_shocks(
            terms, inputs, n_paths=n_paths, seed=seed
        )
    shocks = np.asarray(shocks, dtype=float)
    expected_shape = (len(terms["schedule"]), len(symbols))
    if shocks.ndim != 3 or shocks.shape[1:] != expected_shape:
        raise ValueError(
            f"Shocks must have shape (n_paths, {expected_shape[0]}, {expected_shape[1]})"
        )
    if not np.isfinite(shocks).all():
        raise ValueError("Shocks must be finite")

    observations = [row[0] for row in terms["schedule"]]
    intervals = []
    previous = terms["pricing_date"]
    for observation in observations:
        dt = _year_fraction(previous, observation)
        if dt <= 0:
            raise ValueError("Observation dates must follow the pricing date")
        intervals.append(dt)
        previous = observation

    sigma = np.asarray(volatilities, dtype=float)
    dividend = np.asarray(dividends, dtype=float)
    dt = np.asarray(intervals, dtype=float)[:, None]
    correlated = shocks @ np.asarray(lower, dtype=float).T
    increments = (rate - dividend - 0.5 * sigma * sigma) * dt
    increments = increments + sigma * np.sqrt(dt) * correlated
    initial = np.asarray(
        [float(terms["underlyings"][symbol]["initial"]) for symbol in symbols]
    )
    return initial * np.exp(np.cumsum(increments, axis=1))


def array_paths(price_array, terms, indices):
    """Convert selected array paths to the mapping consumed by evaluate_note."""
    prices = np.asarray(price_array, dtype=float)
    symbols = list(terms["underlyings"])
    observations = [row[0] for row in terms["schedule"]]
    converted = []
    for index in indices:
        converted.append({
            observation: dict(zip(symbols, prices[index, period].tolist(), strict=True))
            for period, observation in enumerate(observations)
        })
    return converted


def select_median_array_path(price_array, terms):
    """Select the actual array path nearest the pointwise normalized median."""
    prices = np.asarray(price_array, dtype=float)
    if prices.ndim != 3 or len(prices) == 0:
        raise ValueError("price_array must contain at least one three-dimensional path")
    initial = np.asarray([
        float(spec["initial"]) for spec in terms["underlyings"].values()
    ])
    normalized = prices / initial
    centre = np.median(normalized, axis=0)
    distances = np.mean((normalized - centre) ** 2, axis=(1, 2))
    index = int(np.argmin(distances))
    return index, array_paths(prices, terms, [index])[0]


def select_median_path(paths, terms):
    """Return the actual simulated path closest to the pointwise median path.

    Prices are normalized by their contractual initial levels before measuring
    squared distance, so every underlying and observation receives equal weight.
    The selected path is a genuine Monte Carlo realization, not a synthetic
    path assembled from median coordinates.
    """
    if not paths:
        raise ValueError("At least one simulated path is required")
    symbols = list(terms["underlyings"])
    observations = [row[0] for row in terms["schedule"]]
    initials = {
        symbol: float(terms["underlyings"][symbol]["initial"])
        for symbol in symbols
    }
    vectors = []
    for path in paths:
        try:
            vector = [
                float(path[observation][symbol]) / initials[symbol]
                for observation in observations
                for symbol in symbols
            ]
        except KeyError as error:
            raise ValueError(f"Path is missing required fixing: {error}") from error
        vectors.append(vector)
    centre = [median(vector[index] for vector in vectors)
              for index in range(len(vectors[0]))]
    distances = [
        sum((value - target) ** 2 for value, target in zip(vector, centre, strict=True))
        / len(centre)
        for vector in vectors
    ]
    selected_index = min(range(len(paths)), key=distances.__getitem__)
    return selected_index, paths[selected_index]
