"""The lever contract. Every lever, specialist and agent result is a LeverImpact.

A lever never computes goal outcomes itself: it describes *what changes* (flows, one-offs,
risks, allocations, goal parameters) and the engine does the rest. New ideas from teammates
become new builders that return this shape; the engine, ranking and UI stay untouched.

Amounts are in today's CHF (the engine indexes them with inflation unless indexed=False).
Sign convention: + = more money for the client, - = less.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .assumptions import Assumption
from .dates import add_months
from .dist import Dist

Bucket = Literal["cash", "invested", "p3a", "p2"]
LeverGroup = Literal["no_lifestyle_cost", "structural", "behavioural", "goal_change", "life_event"]


class OneOff(BaseModel):
    at: date
    amount: Dist
    bucket: Bucket = "cash"
    indexed: bool = True
    label: str = ""


class RecurringDelta(BaseModel):
    start: date
    end: date | None = None
    monthly: Dist
    resample: Literal["once", "yearly", "monthly"] = "once"   # how often a new draw is taken per path
    indexed: bool = True
    behavioural: bool = False       # fades over time (config: market.behavioural_haircut)
    category: str | None = None
    label: str = ""


class ContingentOneOff(BaseModel):
    """A one-off cash flow whose *timing* is uncertain, not just its size (inheritance, business exit).

    `timing` is months-from-plan-start, sampled once per path; mass that falls beyond the simulated
    horizon simply never pays out on that path (the event didn't happen yet, or at all, within the run).
    """
    amount: Dist
    timing: Dist
    bucket: Bucket = "cash"
    indexed: bool = True
    label: str = ""


class Shock(BaseModel):
    start: date
    end: date | None = None
    annual_prob: float
    severity: Dist                  # cost when it happens, positive CHF
    label: str = ""


class IncomeDelta(BaseModel):
    start: date
    end: date | None = None
    salary_factor: float | None = None   # 0.8 = part-time 80%
    monthly_net: Dist | None = None      # additive net income (side business), + or -
    affects_gross: bool = True           # salary factor flows into mortgage affordability and pillar 2
    label: str = ""


class AllocationDelta(BaseModel):
    start: date
    end: date | None = None
    from_bucket: Bucket = "cash"
    to_bucket: Bucket
    mode: Literal["once", "monthly"] = "monthly"
    amount: Dist
    label: str = ""


class Investment(BaseModel):
    """Money committed to one investment (a fund, stock trading, crypto), tracked as its own pot in every simulated
    future with its own expected return and volatility; it moves with the market draws, scaled to its volatility.
    It counts as invested money for goals, and a home purchase can draw on it."""
    start: date
    once: Dist | None = None                # today's CHF moved at start (up to what the source bucket holds)
    monthly: Dist | None = None             # today's CHF moved each month from start
    expected_return: float = 0.045          # per year
    volatility: float = 0.10                # per year
    from_bucket: Bucket = "cash"
    label: str = ""


class Debt(BaseModel):
    """Remaining balance of an unsecured loan, for the chart. Cash flows live on one_offs/recurring."""
    start: date
    principal: float            # today's CHF at origination
    annual_rate: float
    term_months: int
    indexed: bool = True        # principal in today's CHF, like the expense it finances
    label: str = ""


class Withdrawal(BaseModel):
    """State-dependent: take `amount` from buckets in `order`, respecting per-bucket caps (CHF)."""
    at: date
    amount: Dist
    order: list[Bucket] = Field(default_factory=lambda: ["cash", "invested", "p3a"])
    caps: dict[str, float] = Field(default_factory=dict)
    house_indexed: bool = False
    label: str = ""


class GoalChange(BaseModel):
    goal_id: str | None = None           # None = the goal being planned
    field: str                           # "price", "amount", "target_date", "use_pillar2", ...
    op: Literal["set", "mul", "add", "add_months"] = "set"
    value: float
    label: str = ""


class LeverImpact(BaseModel):
    lever_id: str
    title: str
    description: str = ""
    group: LeverGroup = "structural"
    one_offs: list[OneOff] = Field(default_factory=list)
    contingent: list[ContingentOneOff] = Field(default_factory=list)
    recurring: list[RecurringDelta] = Field(default_factory=list)
    shocks: list[Shock] = Field(default_factory=list)
    income_changes: list[IncomeDelta] = Field(default_factory=list)
    allocation_changes: list[AllocationDelta] = Field(default_factory=list)
    investments: list[Investment] = Field(default_factory=list)
    withdrawals: list[Withdrawal] = Field(default_factory=list)
    debts: list[Debt] = Field(default_factory=list)
    goal_changes: list[GoalChange] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)
    confidence: Literal["structural", "behavioural", "estimated"] = "structural"
    effort: Literal["none", "low", "medium", "high"] = "low"
    product_trigger: str | None = None   # advisor view only: "mortgage", "3a", "investment_plan", ...
    excludes: list[str] = Field(default_factory=list)
    origin: Literal["builtin", "specialist", "agent", "user"] = "builtin"
    headline_monthly: float | None = None   # CHF/month shown on the card, when meaningful
    settings: dict[str, str | float] = Field(default_factory=dict)   # scenario-level switches, e.g. {"portfolio": "balanced"}
    details: dict[str, Any] = Field(default_factory=dict)            # specialist data for the "Why?" drawer (tables, options)
    icon: str | None = None

    def shifted(self, months: int) -> "LeverImpact":
        """Same lever, started `months` later (used for the decision deadline)."""
        if months == 0:
            return self

        def mv(d: date | None) -> date | None:
            return None if d is None else add_months(d, months)

        c = self.model_copy(deep=True)
        for o in c.one_offs:
            o.at = mv(o.at)
        for r in c.recurring:
            r.start, r.end = mv(r.start), mv(r.end)
        for s in c.shocks:
            s.start, s.end = mv(s.start), mv(s.end)
        for i in c.income_changes:
            i.start, i.end = mv(i.start), mv(i.end)
        for a in c.allocation_changes:
            a.start, a.end = mv(a.start), mv(a.end)
        for w in c.withdrawals:
            w.at = mv(w.at)
        for d in c.debts:
            d.start = mv(d.start)
        return c
