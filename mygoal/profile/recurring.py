"""Recurring payment detection.

Same normalised merchant and sign, amounts within a tolerance (price changes allowed), and a
regular cadence in {weekly, biweekly, monthly, quarterly, semiannual, yearly}. Annual bills matter
(vehicle tax, Serafe): with less than ~25 months of history they appear only twice, so yearly
cadences need 2 occurrences, everything else 3.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .model import RecurringGroup

PERIODS = [  # label, days, tolerance
    ("weekly", 7, 2), ("biweekly", 14, 3), ("monthly", 30.44, 5), ("quarterly", 91.3, 12),
    ("semiannual", 182.6, 20), ("yearly", 365.25, 25),
]
AMOUNT_TOLERANCE = 0.15
MIN_REGULAR_SHARE = 0.6
MIN_DOMINANCE = 0.5


def _clusters(amounts: np.ndarray) -> list[np.ndarray]:
    order = np.argsort(amounts)
    clusters, current = [], [order[0]]
    for i in order[1:]:
        if amounts[i] > amounts[current[0]] * (1 + AMOUNT_TOLERANCE) + 1.0:
            clusters.append(np.array(current))
            current = [i]
        else:
            current.append(i)
    clusters.append(np.array(current))
    return clusters


def _cadence(dates: list[date]) -> tuple[str, float, float] | None:
    if len(dates) < 2:
        return None
    gaps = np.diff([d.toordinal() for d in dates]).astype(float)
    gaps_nz = gaps[gaps > 3] if (gaps > 3).any() else gaps   # same-day extras (13th salary) don't define cadence
    med = float(np.median(gaps_nz))
    for label, days, tol in PERIODS:
        if abs(med - days) <= tol:
            # a missing export month doubles one gap; still regular
            ok = np.array([min(abs(g - days), abs(g - 2 * days)) <= tol or g <= 3 for g in gaps])
            return label, days, float(ok.mean())
    return None


def detect_recurring(df: pd.DataFrame, as_of: date) -> list[RecurringGroup]:
    """df columns: id, booking_date, amount, merchant, category, tags, counterparty. Internal transfers excluded upstream."""
    out: list[RecurringGroup] = []
    for (merchant, positive), g in df.groupby(["merchant", df["amount"] > 0]):
        if len(g) < 2 or merchant == "unknown":
            continue
        amounts = g["amount"].abs().to_numpy()
        for ci, idx in enumerate(_clusters(amounts)):
            sub = g.iloc[idx].sort_values("booking_date")
            dates = list(sub["booking_date"])
            cad = _cadence(dates)
            if not cad:
                continue
            label, days, regular = cad
            min_count = 2 if label == "yearly" else 3
            if len(sub) < min_count or regular < MIN_REGULAR_SHARE:
                continue
            # a bill dominates its merchant: 7 similar Aldi receipts among 80 are coincidence, not a subscription
            span = g[(g["booking_date"] >= dates[0]) & (g["booking_date"] <= dates[-1])]
            if len(sub) / max(len(span), 1) < MIN_DOMINANCE:
                continue
            # a monthly-looking cluster with several payments per month is spending, not a bill
            per_month = sub.groupby(sub["booking_date"].map(lambda d: (d.year, d.month))).size()
            if label in ("monthly", "quarterly", "semiannual", "yearly") and (per_month > 2).mean() > 0.2:
                continue
            last3 = sub["amount"].tail(3).to_numpy()
            amount = float(np.median(last3))
            last = dates[-1]
            active = (as_of - last).days <= days * 1.5 + 10
            cats = sub["category"].value_counts()
            tags = sorted({t for ts in sub["tags"] for t in ts})
            out.append(RecurringGroup(
                key=f"{merchant}|{'in' if positive else 'out'}|{label}|{ci}",
                merchant=merchant, category=str(cats.index[0]), period_days=int(round(days)), period_label=label,
                amount=round(amount, 2), monthly_equivalent=round(amount * 30.4375 / days, 2), count=len(sub),
                first_date=dates[0], last_date=last, next_expected=last + timedelta(days=int(round(days))),
                active=active, tags=tags, counterparty=next((c for c in sub["counterparty"] if c), None),
                booking_ids=list(sub["id"]),
            ))
    return out
