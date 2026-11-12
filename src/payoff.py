"""Evaluate one absolute-price path on scheduled observation dates (USD per note)."""
from decimal import Decimal as D
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_terms(path=ROOT / "config/product_terms.yaml"):
    terms = yaml.safe_load(path.read_text())
    schedule = terms["schedule"]
    previous = terms["settlement_date"]
    for observation, payment in schedule:
        if not previous < observation <= payment:
            raise ValueError("Check observation/payment order in the terms")
        previous = payment
    if not schedule or schedule[-1][1] != terms["maturity_date"]:
        raise ValueError("Final payment date must equal maturity")
    return terms


def evaluate_note(paths, terms, *, as_of=None):
    """paths[ISO date][symbol] is the closing price. as_of cuts off observations.

    Rows represent amounts due on the associated payment date, even if as_of
    is between fixing and payment. With as_of=None all fixings until exit are required.
    """
    names = terms["underlyings"]
    face = D(terms["principal"])
    coupon = face * D(terms["coupon_rate_annual"]) / terms["coupons_per_year"]
    call = terms["autocall"]
    pending = 0
    rows = []
    call_date = None
    redemption = D(0)
    schedule = terms["schedule"]
    for period, (obs, pay) in enumerate(schedule, start=1):
        if as_of is not None and obs > as_of:
            break
        if obs not in paths or not set(names).issubset(paths[obs]):
            raise ValueError(f"Missing fixing on {obs}: need {list(names)}")
        prices = {s: D(str(paths[obs][s])) for s in names}
        if any(not v.is_finite() or v < 0 for v in prices.values()):
            raise ValueError(f"Invalid price on {obs}")
        ratios = {s: prices[s] / D(names[s]["initial"]) for s in names}
        coupon_due = all(prices[s] >= D(names[s]["coupon_barrier"]) for s in names)
        paid_coupon = (1 + pending) * coupon if coupon_due else D(0)
        pending = 0 if coupon_due or not terms["memory_coupon"] else pending + 1
        status = "outstanding"
        expired = 0
        if period == len(schedule):
            worst = min(ratios, key=ratios.get)
            protected = (prices[worst] >= D(names[worst]["principal_barrier"]) or
                         max(ratios.values()) >= D(terms["maturity"]["best_of_principal_protection_level"]))
            redemption = face if protected else face * ratios[worst]
            status = "matured"
            expired, pending = pending, 0
        elif (call["enabled"] and period >= call["first_period"] and
              min(ratios.values()) >= D(call["level_as_fraction_of_initial"])):
            redemption = face
            call_date = obs
            status = "autocalled"
        rows.append(dict(period=period, observation_date=obs, payment_date=pay, **prices,
                         coupon=paid_coupon, pending_periods=pending, expired_periods=expired,
                         principal=redemption, cashflow=paid_coupon + redemption, status=status))
        if status != "outstanding":
            break
    return dict(rows=rows, coupon_cashflows=[r["coupon"] for r in rows],
                unpaid_memory_coupons=[r["pending_periods"] * coupon for r in rows],
                autocall_date=call_date, redemption_amount=redemption,
                total_cashflow=sum((r["cashflow"] for r in rows), D(0)))
