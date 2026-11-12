"""Rebuild wide daily prices and data-quality evidence from immutable chart responses."""
import csv
import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import Decimal as D, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import yaml

from .payoff import ROOT


def write_rows(path, rows, columns=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=columns or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def expected_sessions(calendar):
    day = date.fromisoformat(calendar["start"])
    end = date.fromisoformat(calendar["end"])
    days = set()
    while day <= end:
        if day.weekday() < 5 and day.isoformat() not in calendar["holidays"]:
            days.add(day.isoformat())
        day += timedelta(days=1)
    return days


def load_market(terms):
    calendar = yaml.safe_load((ROOT / "config/market_calendar.yaml").read_text())
    sessions = expected_sessions(calendar)
    raw_dir = ROOT / "data/raw"
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    close, adjusted, events, quality = {}, {}, [], []
    
    for symbol, spec in terms["underlyings"].items():
        raw = (raw_dir / f"{symbol}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][symbol]["sha256"]:
            raise ValueError(f"{symbol}: snapshot checksum mismatch")
        chart = json.loads(raw, parse_float=D)["chart"]["result"][0]
        meta = chart["meta"]
        if (meta["symbol"], meta["currency"], meta["exchangeTimezoneName"]) != (symbol, "USD", "America/New_York"):
            raise ValueError(f"{symbol}: unexpected identity, currency or timezone")
        zone = ZoneInfo(meta["exchangeTimezoneName"])
        def day_of(timestamp):
            return datetime.fromtimestamp(timestamp, zone).date().isoformat()
        dates = [day_of(t) for t in chart["timestamp"]]
        if len(set(dates)) != len(dates) or set(dates) != sessions:
            raise ValueError(f"{symbol}: duplicate or unmatched sessions; missing={sorted(sessions-set(dates))}, extra={sorted(set(dates)-sessions)}")
        indicator = chart["indicators"]
        for day, value, adj in zip(dates, indicator["quote"][0]["close"],
                                   indicator["adjclose"][0]["adjclose"], strict=True):
            if any(v is None or not D(v).is_finite() or v <= 0 for v in (value, adj)):
                raise ValueError(f"{symbol}: invalid close or adjusted close on {day}")
            close.setdefault(day, {})[symbol] = D(value).quantize(D(".01"), rounding=ROUND_HALF_UP)
            adjusted.setdefault(day, {})[symbol] = D(adj).quantize(D(".000001"))
        actions = chart.get("events", {})
        for kind in ("splits", "dividends"):
            for event in actions.get(kind, {}).values():
                events.append(dict(date=day_of(event["date"]), symbol=symbol, event=kind,
                                   value=event["splitRatio"] if kind == "splits" else event["amount"]))
        initial = close[terms["pricing_date"]][symbol]
        if initial != D(spec["initial"]):
            raise ValueError(f"{symbol}: pricing-date close {initial} differs from contract")
        quality.append(dict(symbol=symbol, first=min(dates), last=max(dates), sessions=len(dates),
                            missing_sessions=0, duplicate_dates=0, missing_prices=0,
                            splits=len(actions.get("splits", {})), dividends=len(actions.get("dividends", {})),
                            initial_close=initial, contract_initial=spec["initial"]))
    processed = ROOT / "data/processed"
    for filename, series in (("prices_close.csv", close), ("prices_adjusted.csv", adjusted)):
        write_rows(processed / filename, [dict(date=d, **series[d]) for d in sorted(series)])
    write_rows(processed / "corporate_actions.csv", sorted(events, key=lambda e: (e["date"], e["symbol"])),
               ["date", "symbol", "event", "value"])
    write_rows(ROOT / "output/tables/data_quality.csv", quality)
    if any(r["splits"] for r in quality):
        raise ValueError("Review split-adjusted closes and contract adjustment before replay.")
    return close
