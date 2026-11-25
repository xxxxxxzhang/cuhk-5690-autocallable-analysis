"""Compare pricing-date copulas using the group's Student-t experiment."""
from copy import deepcopy
from statistics import NormalDist

import numpy as np

from .data_loader import write_rows
from .model import load_model_inputs, simulate_price_array, standard_normal_shocks
from .payoff import ROOT, load_terms
from .valuation import value_price_array


def t5_to_normal(values):
    """Map t(5) values through their exact CDF, then the normal inverse CDF."""
    theta = np.arctan(values / np.sqrt(5))
    probabilities = 0.5 + (
        theta + (2 / 3) * np.sin(2 * theta) + np.sin(4 * theta) / 12
    ) / np.pi
    if np.any((probabilities <= 0) | (probabilities >= 1)):
        raise ValueError("CDF rounded to an endpoint. Higher precision is required.")
    inverse_normal = NormalDist().inv_cdf
    return np.fromiter(
        map(inverse_normal, probabilities.flat), float, count=probabilities.size
    ).reshape(values.shape)


def compare_copulas(terms, inputs):
    """Return results for both dependence structures using paired paths."""
    symbols = list(terms["underlyings"])
    correlation = np.array([
        [inputs["correlation"][left][right] for right in symbols]
        for left in symbols
    ])
    independent = standard_normal_shocks(terms, inputs)
    gaussian = independent @ np.linalg.cholesky(correlation).T

    # One shared scale for the three stocks in each path and quarter.
    chi_squared = np.random.default_rng(5691).chisquare(
        5, size=(*gaussian.shape[:2], 1)
    )
    student = t5_to_normal(gaussian / np.sqrt(chi_squared / 5))

    # Shocks already contain dependence, so the price generator uses identity here.
    ready = deepcopy(inputs)
    ready["correlation"] = {
        left: {right: float(left == right) for right in symbols}
        for left in symbols
    }
    rows = []
    baseline = None
    for name, shocks in [("Gaussian", gaussian), ("Student-t copula (df=5)", student)]:
        prices = simulate_price_array(terms, ready, shocks=shocks)
        result = value_price_array(prices, terms, inputs)
        summary = result["summary"]
        present_values = result["present_values"]
        if baseline is None:
            baseline = present_values.copy()
        paired_difference = present_values - baseline
        paired_se = (
            paired_difference.std(ddof=1) / np.sqrt(len(paired_difference))
            if len(paired_difference) > 1 else 0.0
        )
        joint_low = (
            shocks < NormalDist().inv_cdf(0.05)
        ).all(axis=2).mean()
        rows.append({
            "model": name,
            "pv": present_values.mean(),
            "mc_se": summary["standard_error"],
            "call": summary["autocall_probability"],
            "loss": summary["principal_loss_probability"],
            "worst5": summary["worst_5pct_mean_return"],
            "joint_low": joint_low,
            "paired_diff": paired_difference.mean(),
            "paired_se": paired_se,
            "diff_low": paired_difference.mean() - 1.96 * paired_se,
            "diff_high": paired_difference.mean() + 1.96 * paired_se,
        })
    return rows


def main():
    rows = compare_copulas(load_terms(), load_model_inputs())
    output = ROOT / "output/tables/model_robustness.csv"
    write_rows(output, rows)
    for row in rows:
        print(f'{row["model"]}: PV={row["pv"]:.6f}, loss={row["loss"]:.6%}')
    print(f"Results: {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
