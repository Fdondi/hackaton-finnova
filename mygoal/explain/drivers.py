"""Main-driver sentences. Each driver scores how much it explains the situation; the top ones are shown.
Register more with @driver("name")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..categorise import load_taxonomy
from ..engine import Baseline
from ..engine.solve import GoalOutcome
from ..model import GoalSpec
from ..profile import Profile
from ..registry import Registry
from .texts import chf, month, pct, t


@dataclass
class DriverInput:
    goal: GoalSpec
    outcome: GoalOutcome
    profile: Profile
    base: Baseline
    lang: str


@dataclass
class Driver:
    key: str
    score: float
    text: str


DRIVERS: Registry[Callable[[DriverInput], Driver | None]] = Registry("drivers")


def driver(name: str):
    return DRIVERS.decorator(name)


@driver("binding_constraint")
def binding(d: DriverInput):
    o = d.outcome
    if o.p_success >= 0.7 or not o.binding:
        return None
    if o.binding == "affordability":
        return Driver("affordability", 0.9, t("drivers.affordability", d.lang))
    if o.binding in ("total_equity", "hard_equity", "savings"):
        return Driver("equity", 0.8, t("drivers.equity", d.lang, target=month(o.target_date, d.lang),
                                       need=chf(o.need_at_target), have=chf(o.have_at_target)))
    if o.binding == "capital":
        return Driver("capital", 0.8, t("drivers.capital", d.lang, need=chf(o.need_at_target)))
    return None


@driver("savings_rate")
def savings_rate(d: DriverInput):
    rate = d.profile.savings_rate
    if rate >= 0.2:
        return None
    return Driver("savings_rate", 0.6 + (0.2 - rate), t("drivers.savings_rate", d.lang, rate=pct(max(rate, 0)),
                                                         fcf=chf(d.profile.free_cash_flow_monthly)))


@driver("big_cost")
def big_cost(d: DriverInput):
    tax = load_taxonomy()
    groups = {"car": ("transport_car", "car_financing")}
    car = sum(d.profile.monthly(c) for c in groups["car"])
    candidates = [(car, t("drivers.big_cost", d.lang, category="Your car" if d.lang == "en" else "Ihr Auto", amount=chf(car)))]
    for f in d.profile.flows:
        if f.kind == "spending" and f.category not in ("housing", "taxes", *groups["car"]) and not f.opaque:
            label = tax.label(f.category, d.lang)
            candidates.append((f.monthly, t("drivers.big_cost", d.lang, category=label, amount=chf(f.monthly))))
    amount, text = max(candidates, key=lambda c: c[0])
    income = d.profile.income.salary_net_monthly_avg or 1
    if amount < 0.08 * income:
        return None
    return Driver("big_cost", 0.5 + amount / income, text)


@driver("idle_cash")
def idle_cash(d: DriverInput):
    idle = d.base.cash - 6 * d.base.spending_monthly
    if idle < 10000:
        return None
    return Driver("idle_cash", 0.55, t("drivers.idle_cash", d.lang, amount=chf(d.base.cash)))


@driver("opaque")
def opaque(d: DriverInput):
    if d.profile.opaque_share < 0.1:
        return None
    return Driver("opaque", 0.4 + d.profile.opaque_share, t("drivers.opaque", d.lang, amount=chf(d.profile.opaque_monthly)))


def top_drivers(inp: DriverInput, n: int = 3) -> list[Driver]:
    found = [x for fn in DRIVERS.values() if (x := fn(inp))]
    return sorted(found, key=lambda x: -x.score)[:n]
