"""Run the meeting demonstration from the repository root."""
from decimal import Decimal as D

from .data_loader import load_market, write_rows
from .model import (
    array_paths,
    calibrate_historical,
    load_model_inputs,
    select_median_array_path,
)
from .payoff import ROOT, evaluate_note, load_terms
from .valuation import run_scenario_analysis
from .visualization import (
    plot_coupon_distribution,
    plot_correlation_heatmap,
    plot_exit_distribution,
    plot_maturity_redemption_map,
    plot_nominal_return_distribution,
    plot_parameter_window_comparison,
    plot_prices,
    plot_scenario_sensitivity,
    plot_simulated_paths,
    plot_value_distribution,
)


def print_data_summary(prices, terms):
    """Print a compact summary after the market-data checks have passed."""
    print("=" * 64)
    print("1. DATA PROCESSING")
    print("=" * 64)
    print(f"Symbols                 : {', '.join(terms['underlyings'])}")
    print(f"Data period             : {min(prices)} to {max(prices)}")
    print(f"Trading sessions        : {len(prices)}")
    print("Data validation         : PASSED")


def print_result_summary(title, result, terms, *, as_of=None):
    """Print status and cash-flow details for one evaluated price path."""
    rows = result["rows"]
    total_periods = len(terms["schedule"])

    print(f"\n[{title}]")
    if as_of is not None:
        print(f"As-of date              : {as_of}")
    print(f"Observations processed  : {len(rows)} / {total_periods}")

    if not rows:
        print("Final status            : NO OBSERVATION")
        return

    last = rows[-1]
    status = last["status"]
    coupon_total = sum(result["coupon_cashflows"], D(0))

    print(f"Final status            : {status.upper()}")
    if status == "autocalled":
        print(f"Autocall observation    : Period {last['period']}")
        print(f"Autocall date           : {result['autocall_date']}")
        print(f"Payment date            : {last['payment_date']}")
    elif status == "outstanding":
        print("Autocall                : Not triggered")
        if len(rows) < total_periods:
            next_observation = terms["schedule"][len(rows)][0]
            print(f"Next observation        : {next_observation}")
    elif status == "matured":
        print(f"Maturity observation    : {last['observation_date']}")
        print(f"Maturity payment date   : {last['payment_date']}")

    print(f"Pending memory coupons  : {last['pending_periods']}")
    print(f"Coupon cash flow        : USD {coupon_total:,.4f}")
    print(f"Principal cash flow     : USD {result['redemption_amount']:,.4f}")
    print(f"Total cash flow         : USD {result['total_cashflow']:,.4f}")


def print_sensitivity_summary(rows):
    """Print the most decision-relevant parameter and contract comparisons."""
    by_name = {row["scenario"]: row for row in rows}
    baseline = by_name["historical_baseline"]
    selected = [
        ("historical_baseline", "Historical baseline"),
        ("half_year_window", "Half-year calibration"),
        ("all_vols_plus_25pct", "All volatilities +25%"),
        ("lower_correlation", "Lower correlation"),
        ("higher_correlation", "Higher correlation"),
        ("no_memory_counterfactual", "No Memory counterfactual"),
        ("no_best_protection_counterfactual", "No Best-of protection"),
    ]
    print(
        f"{'Scenario':<28} {'PV (USD)':>10} {'Delta':>10} "
        f"{'Autocall Q':>12} {'Principal loss Q':>18}"
    )
    print("-" * 92)
    for name, label in selected:
        row = by_name[name]
        delta = float(row["pv_usd"]) - float(baseline["pv_usd"])
        print(
            f"{label:<28} {float(row['pv_usd']):>10.2f} {delta:>+10.2f} "
            f"{float(row['call_Q']):>11.2%} "
            f"{float(row['principal_loss_Q']):>17.2%}"
        )

    no_memory = by_name["no_memory_counterfactual"]
    no_best = by_name["no_best_protection_counterfactual"]
    half_year = by_name["half_year_window"]
    high_vol = by_name["all_vols_plus_25pct"]
    print()
    print(
        "Half-year window effect  : "
        f"USD {float(half_year['pv_usd']) - float(baseline['pv_usd']):+.2f}"
    )
    print(
        "All-volatility effect   : "
        f"USD {float(high_vol['pv_usd']) - float(baseline['pv_usd']):+.2f}"
    )
    print(
        "Memory value contribution: "
        f"USD {float(baseline['pv_usd']) - float(no_memory['pv_usd']):.2f}"
    )
    print(
        "Best-of value contribution: "
        f"USD {float(baseline['pv_usd']) - float(no_best['pv_usd']):.2f}"
    )
    print(
        "Best-of loss-Q reduction : "
        f"{float(no_best['principal_loss_Q']) - float(baseline['principal_loss_Q']):.2%}"
    )


def main():
    terms = load_terms()
    prices = load_market(terms)
    out = ROOT / "output/tables"
    history = evaluate_note(prices, terms, as_of=max(prices))
    write_rows(out / "historical_replay.csv", history["rows"])
    plot_prices(prices, terms, result=history, data_cutoff=max(prices))

    model_inputs = load_model_inputs()
    symbols = list(terms["underlyings"])
    adjusted_path = ROOT / "data/processed/prices_adjusted.csv"
    full_calibration = calibrate_historical(
        adjusted_path, "2025-01-02", terms["pricing_date"], symbols
    )
    half_calibration = calibrate_historical(
        adjusted_path, "2025-06-19", terms["pricing_date"], symbols
    )
    analysis = run_scenario_analysis(
        terms, model_inputs, full_calibration, half_calibration
    )
    baseline = analysis["baseline"]
    summary = baseline["summary"]

    def parameter_row(calibration):
        correlation = calibration["correlation"]
        return {
            "window_start": calibration["window_start"],
            "window_end": calibration["window_end"],
            "daily_returns": calibration["daily_returns"],
            **{symbol: calibration["volatilities"][symbol] for symbol in symbols},
            "AMZN_NVDA": correlation["AMZN"]["NVDA"],
            "AMZN_PLTR": correlation["AMZN"]["PLTR"],
            "NVDA_PLTR": correlation["NVDA"]["PLTR"],
        }

    write_rows(out / "parameters.csv", [
        parameter_row(full_calibration), parameter_row(half_calibration)
    ])
    write_rows(out / "scenarios.csv", analysis["scenarios"])
    write_rows(out / "exit_distribution.csv", analysis["exit_distribution"])
    write_rows(out / "monte_carlo_summary.csv", [summary])

    count = len(baseline["paths"])
    step = max(1, count // 40)
    sample_indices = list(range(0, count, step))[:40]
    sample_paths = array_paths(baseline["paths"], terms, sample_indices)
    plot_simulated_paths(sample_paths, terms, total_paths=count)
    plot_value_distribution(
        baseline["present_values"], summary["estimated_value"],
        float(terms["principal"]),
    )
    representative_index, representative_path = select_median_array_path(
        baseline["paths"], terms
    )
    representative_result = evaluate_note(representative_path, terms)
    write_rows(out / "representative_median_path.csv", representative_result["rows"])
    plot_prices(
        representative_path,
        terms,
        filename="representative_median_path.svg",
        title="Representative median simulated path",
        result=representative_result,
        source_note=(
            f"Correlated-GBM path {representative_index + 1:,}; "
            "nearest actual path to the pointwise median"
        ),
    )
    plot_maturity_redemption_map(terms)
    plot_exit_distribution(analysis["exit_distribution"])
    plot_scenario_sensitivity(analysis["scenarios"])
    plot_nominal_return_distribution(baseline["nominal_returns"])
    plot_parameter_window_comparison(
        [full_calibration, half_calibration], analysis["scenarios"]
    )
    plot_correlation_heatmap([full_calibration, half_calibration])
    plot_coupon_distribution(
        baseline["coupon_totals"],
        float(terms["principal"])
        * float(terms["coupon_rate_annual"])
        / int(terms["coupons_per_year"]),
    )

    print_data_summary(prices, terms)
    print("\n" + "=" * 64)
    print("2. PAYOFF RESULTS")
    print("=" * 64)
    print_result_summary("Historical Replay", history, terms, as_of=max(prices))
    print("\n" + "=" * 64)
    print("3. ISSUE-DATE MONTE CARLO VALUATION")
    print("=" * 64)
    print(f"Model                    : {model_inputs['model']}")
    print(f"Simulated paths          : {summary['paths']:,}")
    print(f"Random seed              : {model_inputs['seed']}")
    print(f"Estimated value          : USD {summary['estimated_value']:,.4f}")
    print(f"Standard error           : USD {summary['standard_error']:,.4f}")
    print(f"Autocall probability     : {summary['autocall_probability']:.2%}")
    print(f"Principal-loss probability: {summary['principal_loss_probability']:.2%}")
    print(f"Mean nominal return       : {summary['mean_nominal_return']:.2%}")
    print(f"Median nominal return     : {summary['median_nominal_return']:.2%}")
    print(f"Worst 5% mean return      : {summary['worst_5pct_mean_return']:.2%}")
    print(f"Mean payment time         : {summary['mean_payment_years']:.3f} years")
    print(f"Representative path       : {representative_index + 1:,}")
    print(f"Representative status     : {representative_result['rows'][-1]['status'].upper()}")
    print(f"Representative cash flow  : USD {representative_result['total_cashflow']:,.4f}")
    print("\n" + "=" * 64)
    print("4. SENSITIVITY ANALYSIS")
    print("=" * 64)
    print(f"Scenarios evaluated       : {len(analysis['scenarios'])}")
    print_sensitivity_summary(analysis["scenarios"])
    print()
    print("Tables                    : parameters.csv, scenarios.csv, exit_distribution.csv")
    print("Figures                   : payoff, exit, sensitivity, correlation, coupon distribution")
    print("Current-state extension   : run `python -m src.stress_demo`")


if __name__ == "__main__":
    main()
