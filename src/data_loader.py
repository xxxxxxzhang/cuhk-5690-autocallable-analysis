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
        lineterminator = "\r\n" if path.parent.name == "processed" else "\n"
        writer = csv.DictWriter(
            out,
            fieldnames=columns or list(rows[0]),
            lineterminator=lineterminator,
        )
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


def extend_close_with_current_snapshot(close, terms):
    """Append the separately frozen current close snapshot for replay charts.

    The validated Yahoo archive remains the sole source for pricing-date
    calibration and the main data-quality table.  This function only appends
    later common sessions from ``data/stress/raw`` so that contract replay and
    the historical chart can reach the latest frozen market close without
    rewriting the original archive.
    """
    symbols = list(terms["underlyings"])
    raw_dir = ROOT / "data/stress/raw"
    manifest = json.loads((raw_dir / "manifest.json").read_text())
    requested_end = manifest["requested_range"][1]
    by_symbol = {}

    for symbol in symbols:
        raw = (raw_dir / f"{symbol}.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][symbol]["sha256"]:
            raise ValueError(f"{symbol}: current snapshot checksum mismatch")
        response = json.loads(raw)
        if response["data"]["symbol"] != symbol:
            raise ValueError(f"{symbol}: current snapshot identity mismatch")
        rows = response["data"]["tradesTable"]["rows"]
        values = {}
        for row in rows:
            day = datetime.strptime(row["date"], "%m/%d/%Y").date().isoformat()
            if day in values:
                raise ValueError(f"{symbol}: duplicate current close on {day}")
            value = D(row["close"].replace("$", "").replace(",", ""))
            if not value.is_finite() or value <= 0:
                raise ValueError(f"{symbol}: invalid current close on {day}")
            values[day] = value.quantize(D(".01"), rounding=ROUND_HALF_UP)
        by_symbol[symbol] = values

    common_dates = sorted(
        set.intersection(*(set(by_symbol[symbol]) for symbol in symbols))
    )
    if not common_dates or common_dates[-1] != requested_end:
        raise ValueError(
            f"Current close snapshot does not reach requested end {requested_end}"
        )

    archive_end = max(close)
    extension_dates = [
        day for day in common_dates if archive_end < day <= requested_end
    ]
    if not extension_dates:
        raise ValueError("Current close snapshot contains no later common sessions")

    merged = {day: dict(values) for day, values in close.items()}
    for day in extension_dates:
        merged[day] = {
            symbol: by_symbol[symbol][day]
            for symbol in symbols
        }

    processed = ROOT / "data/processed/prices_close_replay.csv"
    write_rows(
        processed,
        [dict(date=day, **merged[day]) for day in sorted(merged)],
    )
    metadata = {
        "archive_end": archive_end,
        "snapshot_end": requested_end,
        "extension_sessions": len(extension_dates),
        "source": manifest["source"],
    }
    return merged, metadata
