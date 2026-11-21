"""Estimate abnormal returns around a named market event."""
import hashlib
import json
from datetime import datetime

import numpy as np
import yaml

from .payoff import ROOT


def _parse_nasdaq_close(path):
    payload = json.loads(path.read_text())
    data = payload.get("data")
    if not data or not data.get("tradesTable"):
        raise ValueError(f"Missing Nasdaq historical table in {path}")
    rows = data["tradesTable"].get("rows") or []
    prices = {}
    for row in rows:
        day = datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()
        close = float(row["close"].replace("$", "").replace(",", ""))
        if not np.isfinite(close) or close <= 0:
            raise ValueError(f"Invalid close for {data.get('symbol')} on {day}")
        prices[day] = close
    if not prices:
        raise ValueError(f"No prices found in {path}")
    return prices


def _validate_manifest(raw_directory):
    manifest_path = raw_directory / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"Missing event-study manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    for symbol, expected in manifest["files"].items():
        raw = (raw_directory / f"{symbol}.json").read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected["sha256"]:
            raise ValueError(f"{symbol}: event-study snapshot checksum mismatch")


def load_event_prices(config_path=ROOT / "config/event_study.yaml"):
    """Load and align the frozen Nasdaq closes used by the event study."""
    config = yaml.safe_load(config_path.read_text())
    symbols = [*config["targets"], *config["factors"]]
    raw_directory = ROOT / config["raw_directory"]
    _validate_manifest(raw_directory)
    by_symbol = {
        symbol: _parse_nasdaq_close(raw_directory / f"{symbol}.json")
        for symbol in symbols
    }
    dates = sorted(set.intersection(*(set(by_symbol[symbol]) for symbol in symbols)))
    if len(dates) < 40:
        raise ValueError("Too few aligned sessions for an event study")
    prices = np.asarray([
        [by_symbol[symbol][day] for symbol in symbols]
        for day in dates
    ])
    return config, symbols, dates, prices


def _window_dates(return_dates, event_index, window):
    lower, upper = map(int, window)
    start, stop = event_index + lower, event_index + upper + 1
    if start < 0 or stop > len(return_dates):
        raise ValueError(f"Event window {window} falls outside the available returns")
    return return_dates[start:stop]


def run_event_study(config_path=ROOT / "config/event_study.yaml"):
    """Run a two-factor market-model event study for every target.

    Returns are indexed by their ending trading date. The event-date index is
    therefore day zero, while negative and positive offsets are trading days.
    """
    config, symbols, dates, prices = load_event_prices(config_path)
    returns = prices[1:] / prices[:-1] - 1.0
    return_dates = dates[1:]
    column = {symbol: index for index, symbol in enumerate(symbols)}
    factor_columns = [column[symbol] for symbol in config["factors"]]
    output_rows = []
    shock_vectors = {}

    for event_name, event in config["events"].items():
        if event.get("descriptive_only"):
            continue
        event_date = event["event_date"]
        if event_date not in return_dates:
            raise ValueError(f"Event date {event_date} is not a trading session")
        event_index = return_dates.index(event_date)
        estimation_dates = _window_dates(
            return_dates, event_index, event["estimation_window"]
        )
        estimation_indices = [return_dates.index(day) for day in estimation_dates]
        x_estimation = np.column_stack([
            np.ones(len(estimation_indices)),
            returns[estimation_indices][:, factor_columns],
        ])
        shock_vectors[event_name] = {}

        for target in config["targets"]:
            y_estimation = returns[estimation_indices, column[target]]
            coefficients, *_ = np.linalg.lstsq(x_estimation, y_estimation, rcond=None)
            residuals = y_estimation - x_estimation @ coefficients
            degrees = max(1, len(residuals) - len(coefficients))
            residual_sigma = float(np.sqrt((residuals @ residuals) / degrees))

            for window in event["report_windows"]:
                window_dates = _window_dates(return_dates, event_index, window)
                indices = [return_dates.index(day) for day in window_dates]
                x_window = np.column_stack([
                    np.ones(len(indices)),
                    returns[indices][:, factor_columns],
                ])
                actual = returns[indices, column[target]]
                predicted = x_window @ coefficients
                abnormal = actual - predicted
                car = float(abnormal.sum())
                raw_return = float(np.prod(1.0 + actual) - 1.0)
                approximate_z = (
                    car / (residual_sigma * np.sqrt(len(indices)))
                    if residual_sigma > 0 else 0.0
                )
                row = {
                    "event": event_name,
                    "event_date": event_date,
                    "target": target,
                    "window_start": int(window[0]),
                    "window_end": int(window[1]),
                    "sessions": len(indices),
                    "raw_return": raw_return,
                    "car": car,
                    "approximate_z": float(approximate_z),
                    "alpha": float(coefficients[0]),
                    "beta_QQQ": float(coefficients[1]),
                    "beta_SOXX": float(coefficients[2]),
                    "residual_sigma": residual_sigma,
                }
                output_rows.append(row)
                if list(window) == list(event["stress_window"]):
                    shock_vectors[event_name][target] = car

    return {
        "rows": output_rows,
        "shock_vectors": shock_vectors,
        "price_rows": [
            {"date": day, **dict(zip(symbols, values.tolist(), strict=True))}
            for day, values in zip(dates, prices, strict=True)
        ],
    }
