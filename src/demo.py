"""Run the meeting demonstration from the repository root."""
from decimal import Decimal as D

from .data_loader import load_market, write_rows
from .model import load_model_inputs, select_median_path, simulate_paths
from .payoff import ROOT, evaluate_note, load_terms
from .valuation import value_paths
from .visualization import plot_prices, plot_simulated_paths, plot_value_distribution


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


def main():
    terms = load_terms()
    prices = load_market(terms)
    out = ROOT / "output/tables"
    history = evaluate_note(prices, terms, as_of=max(prices))
    write_rows(out / "historical_replay.csv", history["rows"])

    initials = {s: D(a["initial"]) for s, a in terms["underlyings"].items()}
    first, second = [row[0] for row in terms["schedule"][:2]]
    # Keep a full illustrative underlying path for plotting even though the
    # note's contractual cash flows stop when it is autocalled in period two.
    paths = {observation: dict(initials) for observation, _ in terms["schedule"]}
    paths[first]["PLTR"] = D(terms["underlyings"]["PLTR"]["coupon_barrier"]) - D(".01")
    demo = evaluate_note(paths, terms)
    write_rows(out / "synthetic_memory_call.csv", demo["rows"])
    plot_prices(prices, terms, result=history, data_cutoff=max(prices))
    plot_prices(
        paths,
        terms,
        filename="synthetic_prices.svg",
        title="Synthetic memory-and-autocall scenario",
        result=demo,
        source_note="Illustrative deterministic scenario",
    )

    model_inputs = load_model_inputs()
    simulated_paths = simulate_paths(terms, model_inputs)
    valuation = value_paths(simulated_paths, terms, model_inputs)
    summary = valuation["summary"]
    write_rows(out / "monte_carlo_summary.csv", [summary])
    plot_simulated_paths(simulated_paths, terms)
    plot_value_distribution(
        valuation["present_values"], summary["estimated_value"],
        float(terms["principal"]),
    )
    representative_index, representative_path = select_median_path(simulated_paths, terms)
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

    print_data_summary(prices, terms)
    print("\n" + "=" * 64)
    print("2. PAYOFF RESULTS")
    print("=" * 64)
    print_result_summary("Historical Replay", history, terms, as_of=max(prices))
    print_result_summary("Synthetic Memory-and-Autocall Scenario", demo, terms)
    print("\n" + "=" * 64)
    print("3. ILLUSTRATIVE MONTE CARLO VALUATION")
    print("=" * 64)
    print(f"Model                    : {model_inputs['model']}")
    print(f"Simulated paths          : {summary['paths']:,}")
    print(f"Random seed              : {model_inputs['seed']}")
    print(f"Estimated value          : USD {summary['estimated_value']:,.4f}")
    print(f"Standard error           : USD {summary['standard_error']:,.4f}")
    print(f"Autocall probability     : {summary['autocall_probability']:.2%}")
    print(f"Principal-loss probability: {summary['principal_loss_probability']:.2%}")
    print(f"Representative path       : {representative_index + 1:,}")
    print(f"Representative status     : {representative_result['rows'][-1]['status'].upper()}")
    print(f"Representative cash flow  : USD {representative_result['total_cashflow']:,.4f}")
    print("Assumption status        : ILLUSTRATIVE — TEAM REVIEW REQUIRED")


if __name__ == "__main__":
    main()
