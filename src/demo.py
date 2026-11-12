"""Run the meeting demonstration from the repository root."""
from decimal import Decimal as D

from .data_loader import load_market, write_rows
from .payoff import ROOT, evaluate_note, load_terms
from .visualization import plot_prices


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

    print_data_summary(prices, terms)
    print("\n" + "=" * 64)
    print("2. PAYOFF RESULTS")
    print("=" * 64)
    print_result_summary("Historical Replay", history, terms, as_of=max(prices))
    print_result_summary("Synthetic Memory-and-Autocall Scenario", demo, terms)


if __name__ == "__main__":
    main()
