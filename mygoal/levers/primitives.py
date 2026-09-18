"""Lever primitives: the building blocks the what-if agent (and specialists) compose.

Every number is an `Estimate` with a source and, for guesses, a low/high range. The agent can't
pass a bare number, so every figure in its answer is visible and editable in the UI.
Adding a primitive: a params model + a function, registered with @primitive(...). Its JSON schema
becomes a tool option for the LLM and a form for the no-LLM fallback automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, Field

from ..model import (
    AllocationDelta, AssumptionBook, ContingentOneOff, GoalChange, IncomeDelta, LeverImpact, OneOff, RecurringDelta, Shock,
    add_months, fixed, lognormal, triangular,
)
from ..model.assumptions import Source
from ..registry import Registry
from ..swiss import marginal_tax_rate
from .base import LeverContext


class Estimate(BaseModel):
    value: float
    low: float | None = None
    high: float | None = None
    source: Source = "llm_estimate"
    label: str
    unit: str = "CHF"

    def read(self, book: AssumptionBook, key: str) -> float:
        needs = self.source in ("llm_estimate", "market_default")
        return book.get(key, self.value, label=self.label, source=self.source, unit=self.unit,
                        low=self.low, high=self.high, needs_confirmation=needs)

    def dist(self, value: float):
        if self.low is not None and self.high is not None and self.high > self.low:
            shift = value - self.value
            return triangular(self.low + shift, value, self.high + shift)
        return fixed(value)


class Base(BaseModel):
    title: str = Field(description="Short action title, e.g. 'Sell the boat'")
    description: str = ""
    side_effects: list[str] = Field(default_factory=list)
    group: Literal["no_lifestyle_cost", "structural", "behavioural", "goal_change", "life_event"] = "structural"
    effort: Literal["none", "low", "medium", "high"] = "medium"


class RecurringChange(Base):
    monthly_delta: Estimate = Field(description="CHF per month; positive = the client keeps more money")
    start_in_months: int = 0
    duration_months: int | None = None
    behavioural: bool = False
    category: str | None = None


class AssetDispose(Base):
    asset: str
    sale_value: Estimate = Field(description="What selling brings in (CHF, after fees)")
    months_to_sell: int = 2
    running_costs_monthly: Estimate = Field(description="Running costs that stop after the sale (CHF/month, positive)")


class AssetAcquire(Base):
    asset: str
    price: Estimate
    in_months: int = 0
    running_costs_monthly: Estimate


class IncomeChange(Base):
    net_monthly_delta: Estimate = Field(description="Change in net income per month before tax on it; + or -")
    volatility: float = Field(0.0, description="0 = stable, 0.5 = varies a lot month to month")
    start_in_months: int = 0
    duration_months: int | None = None
    taxable_side_income: bool = Field(False, description="True for self-employed side income: tax and social contributions apply")
    salary_factor: float | None = Field(None, description="e.g. 0.8 when moving to 80% part-time")


class OneOffPrimitive(Base):
    amount: Estimate = Field(description="CHF; negative for a cost, positive for money received")
    in_months: int = 0


class ContingentWindfall(Base):
    """A one-off cash inflow at an uncertain future date: inheritance, business sale, litigation payout,
    deferred bonus. Estimate `expected_in_months` from context (e.g. actuarial life expectancy tables for
    an elderly relative's age and sex) rather than asking the client for a specific date or year — only ask
    for the amount if it isn't otherwise known."""
    amount: Estimate = Field(description="CHF received when the event happens")
    expected_in_months: Estimate = Field(description="Median time until the event, in months from today "
                                          "(unit='months'); derive from context, don't ask the client for a date")
    timing_uncertainty: float = Field(0.5, description="0 = happens almost exactly on schedule, "
                                       "1 = could plausibly happen much earlier or much later")


class ShockPrimitive(Base):
    annual_probability: Estimate
    cost: Estimate


class Substitute(Base):
    remove_monthly: Estimate = Field(description="Costs that stop (CHF/month, positive)")
    add_monthly: Estimate = Field(description="Replacement costs (CHF/month, positive)")
    start_in_months: int = 0
    one_off: Estimate | None = None


class Reallocate(Base):
    from_bucket: Literal["cash", "invested", "p3a"] = "cash"
    to_bucket: Literal["cash", "invested", "p3a", "p2"] = "invested"
    once_amount: Estimate | None = None
    monthly_amount: Estimate | None = None
    expected_return: Estimate | None = Field(None, description="Investing: expected yearly return as a share, e.g. 0.10; "
                                             "set with volatility for a strategy (stock trading, crypto, a fund)")
    volatility: float | None = Field(None, description="Investing: yearly volatility as a share, e.g. 0.15 index fund, "
                                     "0.35 active stock trading, 0.7 crypto")


class GoalChangePrimitive(Base):
    field: str = Field(description="Goal parameter, e.g. 'price', 'amount', 'target_date'")
    op: Literal["set", "mul", "add", "add_months"] = "mul"
    value: Estimate


@dataclass
class PrimitiveDef:
    name: str
    params: type[Base]
    build: Callable[[Base, LeverContext, str, AssumptionBook], LeverImpact]
    description: str


PRIMITIVES: Registry[PrimitiveDef] = Registry("primitives")


def primitive(name: str, params: type[Base], description: str):
    def wrap(fn):
        PRIMITIVES.register(name, PrimitiveDef(name, params, fn, description))
        return fn
    return wrap


def _impact(p: Base, lever_id: str, book: AssumptionBook, **kw) -> LeverImpact:
    return LeverImpact(lever_id=lever_id, title=p.title, description=p.description, side_effects=list(p.side_effects),
                       group=p.group, effort=p.effort, assumptions=book.list(), **kw)


@primitive("recurring_change", RecurringChange, "A lasting change in monthly spending (subscriptions, hobby spend, rent).")
def recurring_change(p: RecurringChange, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    start = add_months(ctx.start, p.start_in_months)
    v = p.monthly_delta.read(book, "monthly_delta")
    end = add_months(start, p.duration_months - 1) if p.duration_months else None
    return _impact(p, lever_id, book, confidence="behavioural" if p.behavioural else "estimated",
                   recurring=[RecurringDelta(start=start, end=end, monthly=p.monthly_delta.dist(v), behavioural=p.behavioural,
                                             category=p.category, label=p.title)])


@primitive("asset_dispose", AssetDispose, "Sell something: one-off sale value plus running costs that stop.")
def asset_dispose(p: AssetDispose, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    months = int(book.get("months_to_sell", p.months_to_sell, label="Months until sold", source="llm_estimate", unit="months",
                          low=0, high=24, step=1))
    at = add_months(ctx.start, months)
    sale = p.sale_value.read(book, "sale_value")
    running = p.running_costs_monthly.read(book, "running_costs_monthly")
    impact = _impact(p, lever_id, book, confidence="estimated",
                     one_offs=[OneOff(at=at, amount=p.sale_value.dist(sale), label=f"Sale of {p.asset}")],
                     recurring=[RecurringDelta(start=at, monthly=p.running_costs_monthly.dist(running), label=f"{p.asset} costs stop")])
    return impact


@primitive("asset_acquire", AssetAcquire, "Buy something: one-off price plus new running costs.")
def asset_acquire(p: AssetAcquire, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    at = add_months(ctx.start, p.in_months)
    price = p.price.read(book, "price")
    running = p.running_costs_monthly.read(book, "running_costs_monthly")
    return _impact(p, lever_id, book, confidence="estimated",
                   one_offs=[OneOff(at=at, amount=p.price.dist(price).scaled(-1), label=p.asset)],
                   recurring=[RecurringDelta(start=at, monthly=p.running_costs_monthly.dist(running).scaled(-1), label=f"{p.asset} costs")])


@primitive("income_change", IncomeChange, "Change in income: side business, part-time, raise, sabbatical.")
def income_change(p: IncomeChange, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    start = add_months(ctx.start, p.start_in_months)
    end = add_months(start, p.duration_months - 1) if p.duration_months else None
    delta = p.net_monthly_delta.read(book, "net_monthly_delta")
    recurring, income = [], []
    if delta:
        keep = 1.0
        if p.taxable_side_income and delta > 0:
            tax = book.get("marginal_tax_rate", marginal_tax_rate(ctx.cfg, ctx.client.canton, ctx.profile.income.gross_annual * 0.8),
                           label="Marginal tax rate on extra income", unit="share", source="market_default", low=0.1, high=0.45, step=0.01)
            social = book.get("social_rate", ctx.cfg.get_path("tax.self_employed_social_rate", 0.1),
                              label="Self-employed social contributions", unit="share", source="market_default", low=0.05, high=0.12, step=0.005)
            keep = max(0.0, 1 - tax - social)
        dist = p.net_monthly_delta.dist(delta * keep)
        if p.volatility > 0:
            from ..model.dist import LogNormal
            recurring.append(RecurringDelta(start=start, end=end, resample="monthly", label=p.title,
                                            monthly=LogNormal(median=abs(delta * keep), sigma=p.volatility, sign=1 if delta > 0 else -1)))
        else:
            recurring.append(RecurringDelta(start=start, end=end, monthly=dist, label=p.title))
    if p.salary_factor is not None:
        income.append(IncomeDelta(start=start, end=end, salary_factor=p.salary_factor, label=p.title))
        if p.salary_factor < 1:   # progressive tax: taxes fall a bit faster than income (estimate)
            lower_tax = book.get("tax_reduction_monthly", ctx.profile.monthly("taxes") * (1 - p.salary_factor) * 1.2,
                                 label="Lower taxes per month", unit="CHF/month", source="market_default", step=10)
            recurring.append(RecurringDelta(start=start, end=end, monthly=fixed(lower_tax), label="Lower taxes"))
    return _impact(p, lever_id, book, confidence="estimated", recurring=recurring, income_changes=income)


@primitive("one_off", OneOffPrimitive, "A single payment or windfall at a date (wedding, renovation, inheritance).")
def one_off(p: OneOffPrimitive, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    v = p.amount.read(book, "amount")
    return _impact(p, lever_id, book, confidence="estimated",
                   one_offs=[OneOff(at=add_months(ctx.start, p.in_months), amount=p.amount.dist(v), label=p.title)])


@primitive("contingent_windfall", ContingentWindfall,
           "A one-off cash inflow whose timing is uncertain, not just its size (inheritance, business exit, "
           "deferred payout). Model the timing as a probability distribution derived from context — e.g. actuarial "
           "life expectancy for an elderly relative's estate — instead of asking the client to name a year.")
def contingent_windfall(p: ContingentWindfall, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    amount = p.amount.read(book, "amount")
    months = p.expected_in_months.read(book, "expected_in_months")
    sigma = max(0.05, p.timing_uncertainty)
    return _impact(p, lever_id, book, confidence="estimated",
                   contingent=[ContingentOneOff(amount=p.amount.dist(amount), timing=lognormal(max(months, 0.5), sigma),
                                                label=p.title)])


@primitive("shock", ShockPrimitive, "A risk: something costly that may happen each year (repair, health, damage).")
def shock(p: ShockPrimitive, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    prob = p.annual_probability.read(book, "annual_probability")
    cost = p.cost.read(book, "cost")
    return _impact(p, lever_id, book, confidence="estimated",
                   shocks=[Shock(start=ctx.start, annual_prob=prob, severity=p.cost.dist(cost), label=p.title)])


@primitive("substitute", Substitute, "Replace one thing by another: remove costs X, add basket Y (car -> transit).")
def substitute(p: Substitute, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    start = add_months(ctx.start, p.start_in_months)
    removed = p.remove_monthly.read(book, "remove_monthly")
    added = p.add_monthly.read(book, "add_monthly")
    one_offs = []
    if p.one_off is not None:
        v = p.one_off.read(book, "one_off")
        one_offs.append(OneOff(at=start, amount=p.one_off.dist(v), label=p.title))
    return _impact(p, lever_id, book, confidence="estimated", one_offs=one_offs,
                   recurring=[RecurringDelta(start=start, monthly=p.remove_monthly.dist(removed), label="Costs removed"),
                              RecurringDelta(start=start, monthly=p.add_monthly.dist(added).scaled(-1), label="Replacement costs")])


@primitive("reallocate", Reallocate, "Move money between cash, investments and pillar 3a (once and/or monthly).")
def reallocate(p: Reallocate, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    allocs = []
    if p.once_amount is not None:
        v = p.once_amount.read(book, "once_amount")
        allocs.append(AllocationDelta(start=ctx.start, from_bucket=p.from_bucket, to_bucket=p.to_bucket, mode="once", amount=fixed(v)))
    if p.monthly_amount is not None:
        v = p.monthly_amount.read(book, "monthly_amount")
        allocs.append(AllocationDelta(start=ctx.start, from_bucket=p.from_bucket, to_bucket=p.to_bucket, mode="monthly", amount=fixed(v)))
    settings: dict = {}
    if p.to_bucket == "invested" and p.expected_return is not None:   # the invested money follows this strategy
        settings["portfolio_return"] = p.expected_return.read(book, "expected_return")
    if p.to_bucket == "invested" and p.volatility is not None:
        settings["portfolio_volatility"] = book.get("volatility", float(p.volatility), label="Volatility of the strategy",
                                                    unit="%/yr", source="llm_estimate", low=0.0, high=1.0, step=0.05)
    return _impact(p, lever_id, book, confidence="estimated", allocation_changes=allocs, settings=settings)


@primitive("goal_change", GoalChangePrimitive, "Change the goal itself: cheaper home, smaller amount, later date.")
def goal_change(p: GoalChangePrimitive, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    v = p.value.read(book, "value")
    return _impact(p, lever_id, book, confidence="structural",
                   goal_changes=[GoalChange(field=p.field, op=p.op, value=v, label=p.title)])


def build_primitive(name: str, params: dict | Base, ctx: LeverContext, lever_id: str, key_prefix: str = "") -> LeverImpact:
    """key_prefix keeps assumption keys unique when several primitives form one lever ("0.sale_value")."""
    d = PRIMITIVES.get(name)
    p = params if isinstance(params, Base) else d.params.model_validate(params)
    return d.build(p, ctx, lever_id, AssumptionBook(ctx.overrides.get(lever_id), prefix=key_prefix))


def combine(lever_id: str, title: str, parts: list[LeverImpact], **kw) -> LeverImpact:
    """Merge several primitive impacts into one lever (e.g. sell boat = dispose + stop hobby spend)."""
    merged = LeverImpact(lever_id=lever_id, title=title, **kw)
    seen: set[str] = set()
    for p in parts:
        for f in ("one_offs", "contingent", "recurring", "shocks", "income_changes", "allocation_changes", "withdrawals",
                  "goal_changes", "side_effects"):
            getattr(merged, f).extend(getattr(p, f))
        for a in p.assumptions:
            if a.key not in seen:
                merged.assumptions.append(a)
                seen.add(a.key)
    return merged
