"""Run and explain the election-regime rate/mega-IPO proxy stress analysis."""

from math import log

from .data_loader import write_rows
from .payoff import ROOT
from .stress import run_stress_analysis
from .visualization import (
    plot_event_study_cars,
    plot_election_regime,
    plot_factorial_stress,
    plot_interaction_effect,
)


WIDTH = 104


def _section(number, title):
    print("\n" + "=" * WIDTH)
    print(f"{number}. {title}")
    print("=" * WIDTH)


def _print_current_state(result):
    _section(1, "CURRENT STATE")
    print(f"Valuation date              : {result['valuation_date']}")
    print("Current spots               : " + ", ".join(
        f"{symbol} {value:.2f}" for symbol, value in result["current_spots"].items()
    ))
    print("Contract treatment          : O1-O3 fixed from history; only O4-O12 are simulated")
    print("Paid coupons treatment      : previously paid cash flows are excluded from current PV")


def _print_regime_diagnostic(result):
    regime = result["regime"]
    _section(2, "MIDTERM-ELECTION REGIME DIAGNOSTIC")
    print(f"Regime breakpoint           : {regime['break_date']}")
    print(f"Data as of                  : {regime['as_of']}")
    print("Treatment                   : parameter breakpoint, not an additional spot-price shock")
    print()
    print(
        f"{'Symbol':<8} {'Pre return':>12} {'Post return':>12} "
        f"{'Pre vol':>12} {'Post vol':>12} {'EWMA vol':>12}"
    )
    print("-" * 76)
    for row in regime["comparison_rows"]:
        print(
            f"{row['symbol']:<8} "
            f"{float(row['pre_cumulative_return']):>11.2%} "
            f"{float(row['post_cumulative_return']):>11.2%} "
            f"{float(row['pre_annualized_volatility']):>11.2%} "
            f"{float(row['post_annualized_volatility']):>11.2%} "
            f"{float(row['ewma_annualized_volatility']):>11.2%}"
        )
    observations = regime["comparison_rows"][0]["returns_each_window"]
    print(f"Equal-window observations   : {observations} daily returns before and after the breakpoint")


def _print_forward_parameters(result):
    regime = result["regime"]
    _section(3, "FORWARD VOLATILITY AND CORRELATION PARAMETERS")
    half_life = log(0.5) / log(float(regime["decay"]))
    print(f"EWMA decay / half-life      : {regime['decay']:.2f} / {half_life:.2f} trading days")
    print(
        "Correlation shrinkage       : "
        f"{regime['long_run_correlation_weight']:.0%} long-run + "
        f"{regime['recent_correlation_weight']:.0%} recent EWMA"
    )
    print()
    print(f"{'Parameter':<18} {'Long-run':>12} {'Recent EWMA':>14} {'Used in stress':>16}")
    print("-" * 64)
    for row in regime["parameter_rows"]:
        if row["parameter"] == "volatility":
            label = f"Vol {row['left']}"
        else:
            label = f"Corr {row['left']}-{row['right']}"
        print(
            f"{label:<18} {float(row['long_run']):>11.2%} "
            f"{float(row['ewma']):>13.2%} {float(row['regime']):>15.2%}"
        )


def _print_event_proxy(result):
    _section(4, "MEGA-IPO PROXY EVENT STUDY")
    print(f"Historical source event     : {result['event_shock_source']}")
    print("Interpretation               : proxy for a future mega-IPO capital-reallocation shock")
    print("Not assumed                  : SpaceX lists a second time or the event proves causality")
    print()
    print(f"{'Symbol':<8} {'[-5,+5] CAR':>14} {'Approx. z':>14} {'Applied spot shock':>20}")
    print("-" * 62)
    selected = {
        row["target"]: row
        for row in result["event_study"]["rows"]
        if int(row["window_start"]) == -5 and int(row["window_end"]) == 5
    }
    for symbol, shock in result["event_shock"].items():
        row = selected[symbol]
        print(
            f"{symbol:<8} {float(row['car']):>13.2%} "
            f"{float(row['approximate_z']):>14.2f} {float(shock):>19.2%}"
        )


def _print_stress_results(result):
    _section(5, "CURRENT-STATE STRESS RESULTS")
    print(
        f"{'Scenario':<16} {'PV (USD)':>10} {'MC SE':>9} {'Autocall Q':>12} "
        f"{'Next call Q':>12} {'Principal loss Q':>18}"
    )
    print("-" * 84)
    for row in result["scenarios"]:
        print(
            f"{row['scenario']:<16} {float(row['pv_usd']):>10.2f} "
            f"{float(row['mc_se_usd']):>9.2f} {float(row['autocall_Q']):>11.2%} "
            f"{float(row['next_autocall_Q']):>11.2%} "
            f"{float(row['principal_loss_Q']):>17.2%}"
        )


def _print_effect_decomposition(result):
    _section(6, "EFFECT DECOMPOSITION")
    by_name = {row["scenario"]: row for row in result["scenarios"]}
    legacy = by_name["legacy_current"]
    current = by_name["current_regime"]
    rate = by_name["rate_only"]
    ipo = by_name["ipo_only"]
    joint = by_name["joint"]
    print(
        "Regime-parameter effect   : "
        f"USD {float(current['pv_usd']) - float(legacy['pv_usd']):+.2f} "
        "(current_regime - legacy_current)"
    )
    print(
        "Rate-curve effect         : "
        f"USD {float(rate['pv_usd']) - float(current['pv_usd']):+.2f}"
    )
    print(
        "Mega-IPO proxy effect     : "
        f"USD {float(ipo['pv_usd']) - float(current['pv_usd']):+.2f}"
    )
    print(
        "Joint effect              : "
        f"USD {float(joint['pv_usd']) - float(current['pv_usd']):+.2f}"
    )
    print()
    for row in result["interaction"]:
        if row["metric"] in {"pv_usd", "autocall_Q", "principal_loss_Q"}:
            value = float(row["interaction"])
            if row["metric"] == "pv_usd":
                display_value, unit = value, "USD"
            else:
                display_value, unit = 100.0 * value, "percentage points"
            print(
                f"Nonlinear interaction {row['metric']:<16}: "
                f"{display_value:+.6f} {unit}"
            )


def _print_interpretation(result):
    by_name = {row["scenario"]: row for row in result["scenarios"]}
    legacy = by_name["legacy_current"]
    current = by_name["current_regime"]
    regime_effect = float(current["pv_usd"]) - float(legacy["pv_usd"])
    rate_effect = float(by_name["rate_only"]["pv_usd"]) - float(current["pv_usd"])
    proxy_effect = float(by_name["ipo_only"]["pv_usd"]) - float(current["pv_usd"])
    _section(7, "KEY INTERPRETATION AND LIMITS")
    dominant = "mega-IPO proxy" if abs(proxy_effect) > abs(rate_effect) else "rate curve"
    update_driver = "regime parameters" if abs(regime_effect) > max(
        abs(rate_effect), abs(proxy_effect)
    ) else dominant
    print(f"Largest current-value update : {update_driver}")
    print(f"Dominant added stress factor : {dominant}")
    print("Election treatment           : updates volatility/correlation; does not hit current spots twice")
    print("Event-study treatment        : historical stress proxy; not a causal estimate or forecast")
    print("Probability interpretation   : all Q probabilities are risk-neutral valuation outputs")
    print("Model limits                 : historical parameters, GBM, no implied-volatility surface or jumps")
    print("Output tables                : output/stress/tables/")
    print("Output figures               : output/stress/figures/")


def main():
    result = run_stress_analysis()
    table_directory = ROOT / "output/stress/tables"
    processed_directory = ROOT / "data/event_study/processed"
    write_rows(
        processed_directory / "event_prices.csv",
        result["event_study"]["price_rows"],
    )
    write_rows(
        table_directory / "spacex_event_study.csv",
        result["event_study"]["rows"],
    )
    write_rows(
        table_directory / "stress_scenarios.csv",
        result["scenarios"],
    )
    write_rows(
        table_directory / "stress_exit_distribution.csv",
        result["exit_distribution"],
    )
    write_rows(
        table_directory / "interaction_decomposition.csv",
        result["interaction"],
    )
    write_rows(
        table_directory / "election_regime_parameters.csv",
        result["regime"]["parameter_rows"],
    )
    write_rows(
        table_directory / "election_pre_post_comparison.csv",
        result["regime"]["comparison_rows"],
    )
    state_row = {
        "valuation_date": result["valuation_date"],
        "event_shock_label": result["event_shock_label"],
        "source_event": result["event_shock_source"],
        **{f"{symbol}_spot": value for symbol, value in result["current_spots"].items()},
        **{f"{symbol}_mega_ipo_proxy_CAR": value
           for symbol, value in result["event_shock"].items()},
    }
    write_rows(table_directory / "stress_current_state.csv", [state_row])

    plot_event_study_cars(result["event_study"]["rows"])
    plot_election_regime(result["regime"]["comparison_rows"], result["scenarios"])
    plot_factorial_stress(result["scenarios"])
    plot_interaction_effect(result["scenarios"])

    print("=" * WIDTH)
    print("ELECTION-REGIME RATE / MEGA-IPO PROXY STRESS TEST")
    print("=" * WIDTH)
    _print_current_state(result)
    _print_regime_diagnostic(result)
    _print_forward_parameters(result)
    _print_event_proxy(result)
    _print_stress_results(result)
    _print_effect_decomposition(result)
    _print_interpretation(result)
    print("=" * WIDTH)


if __name__ == "__main__":
    main()
