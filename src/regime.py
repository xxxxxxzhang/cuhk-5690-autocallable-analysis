"""Calibrate a recent volatility/correlation regime without changing live spots."""
import csv
import hashlib
import json
from copy import deepcopy
from datetime import datetime

import numpy as np

from .payoff import ROOT


def _load_regime_prices(symbols, as_of):
    """Merge the long adjusted-close history with the frozen current snapshot."""
    with (ROOT / "data/processed/prices_adjusted.csv").open(
        newline="", encoding="utf-8"
    ) as source:
        prices = {
            row["date"]: [float(row[symbol]) for symbol in symbols]
            for row in csv.DictReader(source)
            if row["date"] <= as_of
        }

    raw_directory = ROOT / "data/stress/raw"
    manifest = json.loads((raw_directory / "manifest.json").read_text())
    by_symbol = {}
    for symbol in symbols:
        raw = (raw_directory / f"{symbol}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][symbol]["sha256"]:
            raise ValueError(f"{symbol}: regime snapshot checksum mismatch")
        response = json.loads(raw)
        rows = response["data"]["tradesTable"]["rows"]
        by_symbol[symbol] = {
            datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat():
                float(row["close"].replace("$", "").replace(",", ""))
            for row in rows
        }

    snapshot_dates = sorted(
        set.intersection(*(set(by_symbol[symbol]) for symbol in symbols))
    )
    for day in snapshot_dates:
        if day > as_of:
            continue
        prices[day] = [by_symbol[symbol][day] for symbol in symbols]
    dates = sorted(day for day, values in prices.items() if all(v > 0 for v in values))
    if not dates or dates[-1] != as_of:
        raise ValueError(f"Regime data do not reach the requested as-of date {as_of}")
    return dates, np.asarray([prices[day] for day in dates], dtype=float)


def _correlation(covariance):
    diagonal = np.diag(covariance)
    if (diagonal <= 0).any():
        raise ValueError("Covariance diagonal must be positive")
    scale = np.sqrt(np.outer(diagonal, diagonal))
    correlation = covariance / scale
    correlation = 0.5 * (correlation + correlation.T)
    np.fill_diagonal(correlation, 1.0)
    return correlation


def _matrix_from_mapping(mapping, symbols):
    return np.asarray([
        [float(mapping[left][right]) for right in symbols]
        for left in symbols
    ])


def _mapping_from_matrix(matrix, symbols):
    return {
        left: dict(zip(symbols, matrix[index].tolist(), strict=True))
        for index, left in enumerate(symbols)
    }


def calibrate_election_regime(base_inputs, symbols, *, break_date, as_of,
                              decay=0.90, long_run_correlation_weight=None,
                              recent_correlation_weight=0.30):
    """Estimate EWMA volatility and a shrunk post-event dependence regime.

    The EWMA recursion uses the full available return history, but a short
    half-life gives the most recent observations dominant weight. For the
    dependence matrix, the noisier EWMA estimate is shrunk toward the original
    long-run correlation matrix.
    """
    decay = float(decay)
    recent_weight = float(recent_correlation_weight)
    long_weight = (
        1.0 - recent_weight if long_run_correlation_weight is None
        else float(long_run_correlation_weight)
    )
    if not 0 < decay < 1:
        raise ValueError("EWMA decay must lie strictly between zero and one")
    if not 0 <= recent_weight <= 1:
        raise ValueError("Recent-correlation weight must lie between zero and one")
    if not 0 <= long_weight <= 1 or not np.isclose(long_weight + recent_weight, 1.0):
        raise ValueError("Long-run and recent correlation weights must sum to one")
    dates, price_array = _load_regime_prices(symbols, as_of)
    if break_date not in dates:
        raise ValueError(f"Break date {break_date} is not an available trading session")
    returns = np.diff(np.log(price_array), axis=0)
    if len(returns) < 60:
        raise ValueError("At least 60 returns are required for regime calibration")

    covariance = np.cov(returns[:60].T, ddof=1)
    for observation in returns[60:]:
        covariance = (
            decay * covariance
            + (1.0 - decay) * np.outer(observation, observation)
        )
    ewma_volatility = np.sqrt(np.diag(covariance) * 252.0)
    ewma_correlation = _correlation(covariance)
    long_correlation = _matrix_from_mapping(base_inputs["correlation"], symbols)
    regime_correlation = (
        long_weight * long_correlation
        + recent_weight * ewma_correlation
    )
    regime_correlation = 0.5 * (regime_correlation + regime_correlation.T)
    np.fill_diagonal(regime_correlation, 1.0)
    if np.linalg.eigvalsh(regime_correlation).min() <= 1e-10:
        raise ValueError("Shrunk regime correlation matrix is not positive definite")

    break_index = dates.index(break_date)
    post_count = len(dates) - break_index - 1
    if post_count < 2 or break_index < post_count:
        raise ValueError("Insufficient equal-length pre/post event windows")
    pre_prices = price_array[break_index - post_count:break_index + 1]
    post_prices = price_array[break_index:]
    pre_returns = np.diff(np.log(pre_prices), axis=0)
    post_returns = np.diff(np.log(post_prices), axis=0)
    pre_volatility = pre_returns.std(axis=0, ddof=1) * np.sqrt(252.0)
    post_volatility = post_returns.std(axis=0, ddof=1) * np.sqrt(252.0)
    pre_correlation = np.corrcoef(pre_returns.T)
    post_correlation = np.corrcoef(post_returns.T)
    pre_cumulative = pre_prices[-1] / pre_prices[0] - 1.0
    post_cumulative = post_prices[-1] / post_prices[0] - 1.0

    long_volatility = np.asarray([
        float(base_inputs["volatilities"][symbol]) for symbol in symbols
    ])
    parameter_rows = []
    comparison_rows = []
    for index, symbol in enumerate(symbols):
        parameter_rows.append({
            "parameter": "volatility",
            "left": symbol,
            "right": "",
            "long_run": float(long_volatility[index]),
            "ewma": float(ewma_volatility[index]),
            "regime": float(ewma_volatility[index]),
            "pre_election": float(pre_volatility[index]),
            "post_election": float(post_volatility[index]),
        })
        comparison_rows.append({
            "symbol": symbol,
            "break_date": break_date,
            "as_of": as_of,
            "returns_each_window": post_count,
            "pre_cumulative_return": float(pre_cumulative[index]),
            "post_cumulative_return": float(post_cumulative[index]),
            "pre_annualized_volatility": float(pre_volatility[index]),
            "post_annualized_volatility": float(post_volatility[index]),
            "ewma_annualized_volatility": float(ewma_volatility[index]),
        })
    for i, left in enumerate(symbols):
        for j in range(i + 1, len(symbols)):
            right = symbols[j]
            parameter_rows.append({
                "parameter": "correlation",
                "left": left,
                "right": right,
                "long_run": float(long_correlation[i, j]),
                "ewma": float(ewma_correlation[i, j]),
                "regime": float(regime_correlation[i, j]),
                "pre_election": float(pre_correlation[i, j]),
                "post_election": float(post_correlation[i, j]),
            })

    return {
        "break_date": break_date,
        "as_of": as_of,
        "decay": decay,
        "long_run_correlation_weight": long_weight,
        "recent_correlation_weight": recent_weight,
        "volatilities": dict(zip(
            symbols, ewma_volatility.tolist(), strict=True
        )),
        "correlation": _mapping_from_matrix(regime_correlation, symbols),
        "ewma_correlation": _mapping_from_matrix(ewma_correlation, symbols),
        "parameter_rows": parameter_rows,
        "comparison_rows": comparison_rows,
    }


def inputs_with_regime(base_inputs, calibration):
    """Return a model-input copy using the calibrated current regime."""
    inputs = deepcopy(base_inputs)
    inputs["volatilities"] = deepcopy(calibration["volatilities"])
    inputs["correlation"] = deepcopy(calibration["correlation"])
    return inputs
