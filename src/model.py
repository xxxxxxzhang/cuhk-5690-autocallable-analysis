"""Generate risk-neutral correlated-GBM paths on contractual observation dates."""
from datetime import date
from math import exp, isfinite, sqrt
from random import Random
from statistics import median

import yaml

from .payoff import ROOT


def load_model_inputs(path=ROOT / "config/model_inputs.yaml"):
    """Load the explicitly provisional Monte Carlo assumptions."""
    inputs = yaml.safe_load(path.read_text())
    if inputs.get("model") != "correlated_gbm":
        raise ValueError("Only model='correlated_gbm' is currently implemented")
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
