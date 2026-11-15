"""Discount simulated note cash flows and summarize a Monte Carlo valuation."""
from copy import deepcopy
from datetime import date
from math import exp, sqrt
from statistics import fmean

import numpy as np

from .model import inputs_with_calibration, simulate_price_array, standard_normal_shocks
from .payoff import evaluate_note


def _year_fraction(start, end):
    return (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.0


def _quantile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def discount_result(result, terms, risk_free_rate):
    """Present value one evaluated path using each contractual payment date."""
    return sum(
        float(row["cashflow"]) * exp(
            -risk_free_rate * _year_fraction(terms["pricing_date"], row["payment_date"])
        )
        for row in result["rows"]
    )


def value_paths(paths, terms, inputs):
    """Evaluate, discount and aggregate already-simulated underlying paths."""
    if not paths:
        raise ValueError("At least one simulated path is required")
    rate = float(inputs["risk_free_rate"])
    face = float(terms["principal"])
    results = [evaluate_note(path, terms) for path in paths]
    present_values = [discount_result(result, terms, rate) for result in results]
    total_cashflows = [float(result["total_cashflow"]) for result in results]
    mean = fmean(present_values)
    standard_error = (
        sqrt(sum((value - mean) ** 2 for value in present_values) / (len(paths) - 1))
        / sqrt(len(paths))
        if len(paths) > 1 else 0.0
    )
    autocalled = sum(result["autocall_date"] is not None for result in results)
    principal_loss = sum(float(result["redemption_amount"]) < face for result in results)
    summary = {
        "model": inputs.get("model", "correlated_gbm"),
        "paths": len(paths),
        "seed": inputs.get("seed", ""),
        "risk_free_rate": rate,
        "estimated_value": mean,
        "standard_error": standard_error,
        "expected_undiscounted_cashflow": fmean(total_cashflows),
        "autocall_probability": autocalled / len(paths),
        "principal_loss_probability": principal_loss / len(paths),
        "pv_min": min(present_values),
        "pv_05": _quantile(present_values, 0.05),
        "pv_median": _quantile(present_values, 0.50),
        "pv_95": _quantile(present_values, 0.95),
        "pv_max": max(present_values),
    }
    return {
        "summary": summary,
        "present_values": present_values,
        "path_results": results,
    }


def evaluate_price_array(price_array, terms, *, memory_coupon=None,
                         best_of_protection=None):
    """Vectorized contractual cash flows for a three-dimensional price array."""
    paths = np.asarray(price_array, dtype=float)
    symbols = list(terms["underlyings"])
    periods = len(terms["schedule"])
    if paths.ndim != 3 or paths.shape[1:] != (periods, len(symbols)):
        raise ValueError(
            f"price_array must have shape (n_paths, {periods}, {len(symbols)})"
        )
    if not np.isfinite(paths).all() or (paths < 0).any():
        raise ValueError("Simulated prices must be finite and non-negative")

    count = len(paths)
    face = float(terms["principal"])
    coupon_amount = (
        face * float(terms["coupon_rate_annual"]) / int(terms["coupons_per_year"])
    )
    memory = terms["memory_coupon"] if memory_coupon is None else memory_coupon
    protection = terms["maturity"].get(
        "best_of_principal_protection_enabled", True
    ) if best_of_protection is None else best_of_protection
    initial = np.asarray([
        float(terms["underlyings"][symbol]["initial"]) for symbol in symbols
    ])
    coupon_barrier = np.asarray([
        float(terms["underlyings"][symbol]["coupon_barrier"]) for symbol in symbols
    ])
    principal_barrier = np.asarray([
        float(terms["underlyings"][symbol]["principal_barrier"]) for symbol in symbols
    ])

    coupons = np.zeros((count, periods))
    principal = np.zeros_like(coupons)
    alive = np.ones(count, dtype=bool)
    pending = np.zeros(count, dtype=int)
    called = np.zeros(count, dtype=bool)
    call = terms["autocall"]

    for period in range(periods):
        spot = paths[:, period, :]
        qualifies = alive & (spot >= coupon_barrier).all(axis=1)
        coupons[qualifies, period] = coupon_amount * (1 + pending[qualifies])
        pending[qualifies] = 0
        if memory:
            pending[alive & ~qualifies] += 1

        period_number = period + 1
        if period < periods - 1 and call["enabled"] and period_number >= call["first_period"]:
            call_level = initial * float(call["level_as_fraction_of_initial"])
            newly_called = alive & (spot >= call_level).all(axis=1)
            principal[newly_called, period] = face
            called |= newly_called
            alive[newly_called] = False

        if period == periods - 1:
            ratios = spot / initial
            worst_index = ratios.argmin(axis=1)
            rows = np.arange(count)
            worst_ratio = ratios[rows, worst_index]
            breached = spot[rows, worst_index] < principal_barrier[worst_index]
            best_reaches_initial = (
                ratios.max(axis=1)
                >= float(terms["maturity"]["best_of_principal_protection_level"])
            )
            loss = alive & breached
            if protection:
                loss &= ~best_reaches_initial
            principal[alive, period] = face
            principal[loss, period] = face * worst_ratio[loss]

    exit_period = np.where(called, principal.argmax(axis=1), periods - 1)
    return {
        "coupons": coupons,
        "principal": principal,
        "called": called,
        "exit_period": exit_period,
        "coupon_amount": coupon_amount,
    }


def value_price_array(price_array, terms, inputs, *, memory_coupon=None,
                      best_of_protection=None):
    """Value a vectorized price array and return report-ready risk metrics."""
    evaluated = evaluate_price_array(
        price_array,
        terms,
        memory_coupon=memory_coupon,
        best_of_protection=best_of_protection,
    )
    coupons = evaluated["coupons"]
    principal = evaluated["principal"]
    called = evaluated["called"]
    exit_period = evaluated["exit_period"]
    rate = float(inputs["risk_free_rate"])
    face = float(terms["principal"])
    payment_dates = [payment for _observation, payment in terms["schedule"]]
    payment_years = np.asarray([
        _year_fraction(terms["pricing_date"], payment) for payment in payment_dates
    ])
    discount = np.exp(-rate * payment_years)
    total_by_period = coupons + principal
    present_values = total_by_period @ discount
    nominal_returns = total_by_period.sum(axis=1) / face - 1.0
    principal_loss = principal.sum(axis=1) < face
    mean = float(present_values.mean())
    standard_error = float(present_values.std(ddof=1) / np.sqrt(len(present_values)))
    tail_count = max(1, int(len(nominal_returns) * 0.05))
    worst_tail = np.partition(nominal_returns, tail_count - 1)[:tail_count]
    coupon_amount = evaluated["coupon_amount"]

    summary = {
        "model": inputs.get("model", "correlated_gbm"),
        "paths": len(present_values),
        "seed": inputs.get("seed", ""),
        "risk_free_rate": rate,
        "estimated_value": mean,
        "standard_error": standard_error,
        "expected_undiscounted_cashflow": float(total_by_period.sum(axis=1).mean()),
        "autocall_probability": float(called.mean()),
        "principal_loss_probability": float(principal_loss.mean()),
        "negative_nominal_return_probability": float((nominal_returns < 0).mean()),
        "mean_coupon": float(coupons.sum(axis=1).mean()),
        "mean_nominal_return": float(nominal_returns.mean()),
        "median_nominal_return": float(np.median(nominal_returns)),
        "p05_nominal_return": float(np.quantile(nominal_returns, 0.05)),
        "worst_5pct_mean_return": float(worst_tail.mean()),
        "mean_payment_years": float(payment_years[exit_period].mean()),
        "memory_recovery_probability": float((coupons > coupon_amount).any(axis=1).mean()),
        "pv_min": float(present_values.min()),
        "pv_05": float(np.quantile(present_values, 0.05)),
        "pv_median": float(np.median(present_values)),
        "pv_95": float(np.quantile(present_values, 0.95)),
        "pv_max": float(present_values.max()),
    }
    exit_rows = []
    for index, (observation, payment) in enumerate(terms["schedule"]):
        exit_rows.append({
            "period": index + 1,
            "observation": observation,
            "payment": payment,
            "autocall_Q": float(((exit_period == index) & called).mean()),
            "maturity_Q": float(((exit_period == index) & ~called).mean()),
        })
    return {
        "summary": summary,
        "present_values": present_values,
        "nominal_returns": nominal_returns,
        "coupon_totals": coupons.sum(axis=1),
        "exit_distribution": exit_rows,
        "paths": np.asarray(price_array, dtype=float),
    }


def _correlation_blend(correlation, symbols, target, weight=0.35):
    matrix = np.asarray([
        [float(correlation[left][right]) for right in symbols]
        for left in symbols
    ])
    blended = (1.0 - weight) * matrix + weight * target
    return {
        left: dict(zip(symbols, blended[index].tolist(), strict=True))
        for index, left in enumerate(symbols)
    }


def run_scenario_analysis(terms, base_inputs, full_calibration, half_calibration):
    """Run the handed-off ten-scenario analysis using common random numbers."""
    symbols = list(terms["underlyings"])
    count = int(base_inputs["n_paths"])
    shocks = standard_normal_shocks(terms, base_inputs, n_paths=count)
    historical = inputs_with_calibration(base_inputs, full_calibration)
    half_year = inputs_with_calibration(base_inputs, half_calibration)

    development = deepcopy(base_inputs)
    development["risk_free_rate"] = 0.04
    development["volatilities"] = dict(zip(symbols, (0.35, 0.50, 0.55), strict=True))
    development_matrix = np.asarray([
        [1.00, 0.55, 0.45],
        [0.55, 1.00, 0.60],
        [0.45, 0.60, 1.00],
    ])
    development["correlation"] = {
        left: dict(zip(symbols, development_matrix[index].tolist(), strict=True))
        for index, left in enumerate(symbols)
    }
    pltr_changed = deepcopy(development)
    pltr_changed["volatilities"]["PLTR"] = full_calibration["volatilities"]["PLTR"]

    high_volatility = deepcopy(historical)
    high_volatility["volatilities"] = {
        symbol: 1.25 * float(value)
        for symbol, value in historical["volatilities"].items()
    }
    lower_correlation = deepcopy(historical)
    lower_correlation["correlation"] = _correlation_blend(
        historical["correlation"], symbols, np.eye(len(symbols))
    )
    higher_correlation = deepcopy(historical)
    higher_correlation["correlation"] = _correlation_blend(
        historical["correlation"], symbols, np.ones((len(symbols), len(symbols)))
    )
    high_vol_low_corr = deepcopy(high_volatility)
    high_vol_low_corr["correlation"] = deepcopy(lower_correlation["correlation"])

    scenarios = [
        ("development", development, None, None),
        ("development_only_PLTR_changed", pltr_changed, None, None),
        ("historical_baseline", historical, None, None),
        ("half_year_window", half_year, None, None),
        ("all_vols_plus_25pct", high_volatility, None, None),
        ("lower_correlation", lower_correlation, None, None),
        ("higher_correlation", higher_correlation, None, None),
        ("high_vol_and_low_correlation", high_vol_low_corr, None, None),
        ("no_memory_counterfactual", historical, False, None),
        ("no_best_protection_counterfactual", historical, None, False),
    ]

    rows, exit_rows, baseline = [], [], None
    for name, inputs, memory, protection in scenarios:
        prices = simulate_price_array(terms, inputs, shocks=shocks)
        result = value_price_array(
            prices,
            terms,
            inputs,
            memory_coupon=memory,
            best_of_protection=protection,
        )
        summary = result["summary"]
        rows.append({
            "scenario": name,
            "pv_usd": summary["estimated_value"],
            "mc_se_usd": summary["standard_error"],
            "call_Q": summary["autocall_probability"],
            "principal_loss_Q": summary["principal_loss_probability"],
            "negative_nominal_return_Q": summary["negative_nominal_return_probability"],
            "mean_coupon_usd": summary["mean_coupon"],
            "p05_nominal_return_Q": summary["p05_nominal_return"],
            "mean_nominal_return_Q": summary["mean_nominal_return"],
            "median_nominal_return_Q": summary["median_nominal_return"],
            "worst_5pct_mean_return_Q": summary["worst_5pct_mean_return"],
            "mean_payment_years": summary["mean_payment_years"],
            "memory_recovery_Q": summary["memory_recovery_probability"],
        })
        for row in result["exit_distribution"]:
            exit_rows.append({"scenario": name, **row})
        if name == "historical_baseline":
            baseline = result
    return {"scenarios": rows, "exit_distribution": exit_rows, "baseline": baseline}
