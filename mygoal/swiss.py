"""Small Swiss-rules helpers shared by levers and specialists. Numbers live in config/*.yaml."""
from __future__ import annotations

from datetime import date

from .config import Config


def marginal_tax_rate(cfg: Config, canton: str | None, taxable_income: float) -> float:
    table = cfg.get_path("tax.marginal_rate", {})
    rows = table.get(canton or "", table.get("default"))
    for upper, rate in rows:
        if taxable_income <= upper:
            return float(rate)
    return float(rows[-1][1])


def next_january(d: date) -> date:
    return date(d.year + 1, 1, 1)


def fmt_chf(x: float) -> str:
    return f"CHF {x:,.0f}".replace(",", "'")
