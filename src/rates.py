"""Simple continuously-compounded rate curves for stress valuation."""
import csv
from dataclasses import dataclass
from math import exp, log

import numpy as np


@dataclass(frozen=True)
class RateCurve:
    """Continuously-compounded zero-rate curve with linear interpolation."""

    tenors: tuple
    zero_rates: tuple
    as_of: str = ""
    name: str = ""

    def __post_init__(self):
        tenors = np.asarray(self.tenors, dtype=float)
        rates = np.asarray(self.zero_rates, dtype=float)
        if tenors.ndim != 1 or rates.ndim != 1 or len(tenors) != len(rates):
            raise ValueError("Curve tenors and zero rates must be equal-length vectors")
        if len(tenors) == 0 or not np.isfinite(tenors).all() or not np.isfinite(rates).all():
            raise ValueError("Curve inputs must be non-empty and finite")
        if (tenors <= 0).any() or (np.diff(tenors) <= 0).any():
            raise ValueError("Curve tenors must be positive and strictly increasing")

    def zero_rate(self, maturity_years):
        """Return an interpolated zero rate, flat-extrapolated at both ends."""
        maturity = float(maturity_years)
        if maturity < 0:
            raise ValueError("Maturity cannot be negative")
        return float(np.interp(maturity, self.tenors, self.zero_rates))

    def discount_factor(self, maturity_years):
        maturity = float(maturity_years)
        if maturity < 0:
            raise ValueError("Maturity cannot be negative")
        return exp(-self.zero_rate(maturity) * maturity)

    def forward_rate(self, start_years, end_years):
        """Return the continuously-compounded forward rate over one interval."""
        start, end = float(start_years), float(end_years)
        if start < 0 or end <= start:
            raise ValueError("Forward-rate interval must satisfy 0 <= start < end")
        start_discount = self.discount_factor(start)
        end_discount = self.discount_factor(end)
        return -log(end_discount / start_discount) / (end - start)

    def parallel_shift(self, basis_points, *, name=None):
        shift = float(basis_points) / 10_000.0
        return RateCurve(
            self.tenors,
            tuple(float(rate) + shift for rate in self.zero_rates),
            as_of=self.as_of,
            name=name or f"{self.name}_{basis_points:+g}bp",
        )


def flat_curve(rate, *, as_of="", name="flat"):
    """Represent a flat continuously-compounded curve with the same interface."""
    value = float(rate)
    if not np.isfinite(value):
        raise ValueError("Flat rate must be finite")
    return RateCurve((0.000001, 100.0), (value, value), as_of=as_of, name=name)


def load_rate_curve(path, *, name="current_treasury_proxy"):
    """Load tenor/rate pairs from a CSV file.

    The supplied H.15 constant-maturity yields are explicitly treated as
    continuously-compounded zero-rate proxies for this classroom stress test.
    """
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise ValueError(f"No curve points in {path}")
    as_of = rows[0].get("as_of", "")
    if any(row.get("as_of", "") != as_of for row in rows):
        raise ValueError("All curve points must share one as-of date")
    ordered = sorted(rows, key=lambda row: float(row["tenor_years"]))
    return RateCurve(
        tuple(float(row["tenor_years"]) for row in ordered),
        tuple(float(row["zero_rate"]) for row in ordered),
        as_of=as_of,
        name=name,
    )
