from __future__ import annotations

from datetime import date


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    return date(y, m + 1, 1)


def months_between(a: date, b: date) -> int:
    """Whole months from month(a) to month(b)."""
    return (b.year - a.year) * 12 + (b.month - a.month)


def ym(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"
