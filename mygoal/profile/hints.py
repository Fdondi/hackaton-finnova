"""Asset / situation hints: "you seem to have a car", "you pay into 3a", "you run a side business".

Detectors are plugins: any module can register one with @hint_detector("name").
Specialists (e.g. specialists/car.py) register their own detector next to their levers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from ..categorise import Taxonomy
from ..model import Dataset
from ..registry import Registry
from .model import AssetHint, CategoryFlow, RecurringGroup


@dataclass
class HintContext:
    ds: Dataset
    window: pd.DataFrame        # external bookings in the analysis window (covered months only)
    history: pd.DataFrame       # all external bookings
    recurring: list[RecurringGroup]
    flows: dict[str, CategoryFlow]
    covered_months: int
    taxonomy: Taxonomy

    def monthly_by_tag(self, tag: str) -> tuple[float, list[str]]:
        rows = self.window[self.window["tags"].map(lambda ts: tag in ts)]
        return -float(rows["amount"].sum()) / max(self.covered_months, 1), sorted(set(rows["merchant"]))

    def rows_by_category(self, *categories: str) -> pd.DataFrame:
        return self.window[self.window["category"].isin(categories)]


HINT_DETECTORS: Registry[Callable[[HintContext], list[AssetHint]]] = Registry("hint_detectors")


def hint_detector(name: str):
    return HINT_DETECTORS.decorator(name)


@hint_detector("pillar3a")
def detect_3a(ctx: HintContext) -> list[AssetHint]:
    f = ctx.flows.get("savings_3a")
    has_account = any(a.type == "3a" for a in ctx.ds.accounts) or bool(ctx.ds.client.pension.pillar3a_balance)
    if f and f.monthly > 0:
        rows = ctx.rows_by_category("savings_3a")
        return [AssetHint(kind="pillar3a", label="Pays into pillar 3a", monthly_cost=f.monthly,
                          evidence=sorted(set(rows["merchant"])), booking_ids=list(rows["id"]),
                          details={"annual_contribution": round(f.monthly * 12)}, confidence=0.9)]
    return [AssetHint(kind="no_pillar3a", label="No pillar 3a contributions seen",
                      details={"has_account": has_account}, confidence=0.6)]


@hint_detector("securities")
def detect_securities(ctx: HintContext) -> list[AssetHint]:
    value = sum(a.balance for a in ctx.ds.accounts if a.type == "securities") + sum(p.value for p in ctx.ds.positions)
    if value > 0:
        return [AssetHint(kind="securities", label="Holds securities", details={"value": round(value)}, confidence=0.95)]
    return []


@hint_detector("property")
def detect_property(ctx: HintContext) -> list[AssetHint]:
    rows = ctx.window[ctx.window["tags"].map(lambda ts: "mortgage" in ts)]
    if len(rows):
        return [AssetHint(kind="property", label="Owns property (mortgage payments)",
                          monthly_cost=-float(rows["amount"].sum()) / ctx.covered_months,
                          evidence=sorted(set(rows["merchant"])), booking_ids=list(rows["id"]), confidence=0.8)]
    if any(a.type == "mortgage" for a in ctx.ds.accounts):
        return [AssetHint(kind="property", label="Owns property (mortgage account)", confidence=0.9)]
    return []


ASSET_TAGS = {"boat", "horse", "motorbike", "holiday_home"}   # hobbies that are also sellable assets
GENERIC_TAGS = {"hobby", "books", "events", "cinema", "sport", "swimming", "family_outing"}


@hint_detector("hobbies")
def detect_hobbies(ctx: HintContext) -> list[AssetHint]:
    """Tagged leisure spending becomes a hobby/asset hint. Tags that share the same merchants are one hint."""
    rows = ctx.window[ctx.window["category"] == "leisure_hobby"]
    by_merchants: dict[tuple, list[str]] = {}
    for tag in sorted({t for ts in rows["tags"] for t in ts} - GENERIC_TAGS):
        tagged = rows[rows["tags"].map(lambda ts: tag in ts)]
        by_merchants.setdefault(tuple(sorted(set(tagged["merchant"]))), []).append(tag)
    out = []
    for merchants, tags in by_merchants.items():
        monthly, _ = ctx.monthly_by_tag(tags[0])
        if monthly < 20:
            continue
        asset = next((t for t in tags if t in ASSET_TAGS), None)
        ids = list(rows[rows["merchant"].isin(merchants)]["id"])
        out.append(AssetHint(kind=asset or "hobby", label=f"Spends on {' / '.join(tags)}", monthly_cost=round(monthly, 2),
                             evidence=list(merchants), booking_ids=ids, details={"tags": tags}, confidence=0.6))
    return out


@hint_detector("side_income")
def detect_side_income(ctx: HintContext) -> list[AssetHint]:
    rows = ctx.window[(ctx.window["category"] == "income_other") & (ctx.window["amount"] > 0)
                      & ~ctx.window["text"].str.contains("zins|dividend", case=False, regex=True)
                      & ~ctx.window["tags"].map(lambda ts: "child_allowance" in ts)]
    if rows.empty:
        return []
    monthly = float(rows["amount"].sum()) / ctx.covered_months
    if monthly < 100:
        return []
    by_merchant = rows.groupby("merchant")["amount"].sum().sort_values(ascending=False)
    return [AssetHint(kind="side_income", label="Regular income besides salary", monthly_cost=-round(monthly, 2),
                      evidence=list(by_merchant.index[:5]), booking_ids=list(rows["id"]),
                      details={"monthly_income": round(monthly, 2)}, confidence=0.6)]
