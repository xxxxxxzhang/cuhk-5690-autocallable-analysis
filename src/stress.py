"""Current-state factorial stress analysis for the live structured note."""
import csv
import hashlib
import json
from copy import deepcopy
from datetime import datetime

import numpy as np
import yaml

from .event_study import run_event_study
from .model import simulate_remaining_price_array
from .payoff import ROOT, load_terms
from .rates import flat_curve, load_rate_curve
from .regime import calibrate_election_regime, inputs_with_regime
from .valuation import value_remaining_price_array


def _validate_snapshot_manifest(raw_directory):
    manifest = json.loads((raw_directory / "manifest.json").read_text())
    for symbol, expected in manifest["files"].items():
        raw = (raw_directory / f"{symbol}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
            raise ValueError(f"{symbol}: stress snapshot checksum mismatch")


def _load_current_spots(valuation_date, symbols):
    raw_directory = ROOT / "data/stress/raw"
    _validate_snapshot_manifest(raw_directory)
    spots = {}
    for symbol in symbols:
        response = json.loads((raw_directory / f"{symbol}.json").read_text())
        rows = response["data"]["tradesTable"]["rows"]
        closes = {
            datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat():
                float(row["close"].replace("$", "").replace(",", ""))
            for row in rows
        }
        if valuation_date not in closes:
            raise ValueError(f"{symbol}: no close on valuation date {valuation_date}")
        spots[symbol] = closes[valuation_date]
    return spots


def _load_past_fixings(terms, valuation_date):
    with (ROOT / "data/processed/prices_close.csv").open(
        newline="", encoding="utf-8"
    ) as source:
        by_date = {row["date"]: row for row in csv.DictReader(source)}
    fixings = {}
    symbols = list(terms["underlyings"])
    for observation, _payment in terms["schedule"]:
        if observation > valuation_date:
            break
        if observation not in by_date:
            raise ValueError(f"Missing processed close on {observation}")
        fixings[observation] = {
            symbol: float(by_date[observation][symbol]) for symbol in symbols
        }
    return fixings


def _scenario_row(name, result, *, apply_event_shock, event_shock_label,
                  parameter_set, curve_name, spots):
    summary = result["summary"]
    return {
        "scenario": name,
        "rate_curve": curve_name,
        "parameter_set": parameter_set,
        "event_shock_label": event_shock_label,
        "apply_event_shock": apply_event_shock,
        "AMZN_start": spots["AMZN"],
        "NVDA_start": spots["NVDA"],
        "PLTR_start": spots["PLTR"],
        "pv_usd": summary["estimated_value"],
        "mc_se_usd": summary["standard_error"],
        "pv_05_usd": summary["pv_05"],
        "pv_median_usd": summary["pv_median"],
        "pv_95_usd": summary["pv_95"],
        "autocall_Q": summary["autocall_probability"],
        "next_coupon_Q": summary["next_coupon_probability"],
        "next_autocall_Q": summary["next_autocall_probability"],
        "principal_loss_Q": summary["principal_loss_probability"],
        "mean_future_coupon_usd": summary["mean_future_coupon"],
    }


def run_stress_analysis(config_path=ROOT / "config/stress_scenarios.yaml"):
    """Run the current-regime rate/common-equity-shock factorial design."""
    config = yaml.safe_load(config_path.read_text())
    terms = load_terms()
    inputs = yaml.safe_load((ROOT / "config/model_inputs.yaml").read_text())
    inputs = deepcopy(inputs)
    inputs["n_paths"] = int(config["n_paths"])
    inputs["seed"] = int(config["seed"])
    valuation_date = config["valuation_date"]
    symbols = list(terms["underlyings"])
    current_spots = _load_current_spots(valuation_date, symbols)
    past_fixings = _load_past_fixings(terms, valuation_date)
    regime_config = config["regime"]
    regime_calibration = calibrate_election_regime(
        inputs,
        symbols,
        break_date=regime_config["break_date"],
        as_of=regime_config["as_of"],
        decay=regime_config["ewma_decay"],
        long_run_correlation_weight=regime_config[
            "long_run_correlation_weight"
        ],
        recent_correlation_weight=regime_config["recent_correlation_weight"],
    )
    regime_inputs = inputs_with_regime(inputs, regime_calibration)
    parameter_sets = {"legacy": inputs, "regime": regime_inputs}

    base_curve = flat_curve(
        config["base_rate"]["rate"],
        as_of=valuation_date,
        name="issue_date_flat_3.53pct",
    )
    current_curve = load_rate_curve(ROOT / config["current_curve"])
    curves = {"base": base_curve, "current": current_curve}

    event_result = run_event_study()
    event_name = config["event_study"]
    shock_vector = event_result["shock_vectors"][event_name]
    if set(shock_vector) != set(symbols):
        raise ValueError("Event proxy shock vector does not match note underlyings")
    if any(1.0 + float(shock_vector[symbol]) <= 0 for symbol in symbols):
        raise ValueError("Event proxy shock would create a non-positive stock price")

    first_future = next(
        index for index, (observation, _payment) in enumerate(terms["schedule"])
        if observation > valuation_date
    )
    future_periods = len(terms["schedule"]) - first_future
    shocks = np.random.default_rng(inputs["seed"]).standard_normal(
        (inputs["n_paths"], future_periods, len(symbols))
    )

    rows, exit_rows, scenario_results = [], [], {}
    for scenario in config["scenarios"]:
        name = scenario["name"]
        curve = curves[scenario["rate"]]
        apply_event_shock = bool(scenario["apply_event_shock"])
        parameter_set = scenario["parameter_set"]
        scenario_inputs = parameter_sets[parameter_set]
        scenario_spots = {
            symbol: current_spots[symbol] * (
                1.0 + float(shock_vector[symbol]) if apply_event_shock else 1.0
            )
            for symbol in symbols
        }
        paths, period = simulate_remaining_price_array(
            terms,
            scenario_inputs,
            valuation_date=valuation_date,
            current_spots=scenario_spots,
            past_fixings=past_fixings,
            rate_curve=curve,
            shocks=shocks,
        )
        result = value_remaining_price_array(
            paths,
            terms,
            valuation_date=valuation_date,
            first_future_period=period,
            rate_curve=curve,
        )
        scenario_results[name] = result
        rows.append(_scenario_row(
            name,
            result,
            apply_event_shock=apply_event_shock,
            event_shock_label=config["event_shock_label"],
            parameter_set=parameter_set,
            curve_name=curve.name,
            spots=scenario_spots,
        ))
        for exit_row in result["exit_distribution"]:
            exit_rows.append({"scenario": name, **exit_row})

    required = {"legacy_current", "current_regime", "rate_only", "ipo_only", "joint"}
    by_name = {row["scenario"]: row for row in rows}
    if set(by_name) != required:
        raise ValueError(f"Stress scenarios must be exactly {sorted(required)}")
    interaction_metrics = [
        "pv_usd",
        "autocall_Q",
        "next_coupon_Q",
        "next_autocall_Q",
        "principal_loss_Q",
    ]
    interaction_rows = []
    for metric in interaction_metrics:
        value = (
            by_name["joint"][metric]
            - by_name["rate_only"][metric]
            - by_name["ipo_only"][metric]
            + by_name["current_regime"][metric]
        )
        interaction_rows.append({"metric": metric, "interaction": value})

    return {
        "valuation_date": valuation_date,
        "current_spots": current_spots,
        "event_shock_label": config["event_shock_label"],
        "event_shock_source": event_name,
        "event_shock": shock_vector,
        "regime": regime_calibration,
        "event_study": event_result,
        "scenarios": rows,
        "exit_distribution": exit_rows,
        "interaction": interaction_rows,
        "results": scenario_results,
    }
