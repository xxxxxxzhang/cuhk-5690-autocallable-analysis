"""Discount simulated note cash flows and summarize a Monte Carlo valuation."""
from datetime import date
from math import exp, sqrt
from statistics import fmean

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
