"""Cheap, generic levers every client gets checked for."""
from __future__ import annotations

import re

from ..model import AllocationDelta, GoalChange, Investment, LeverImpact, RecurringDelta, add_months, fixed
from ..swiss import fmt_chf, marginal_tax_rate
from .base import LeverContext, lever


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


@lever("invest_idle_cash")
def invest_idle_cash(ctx: LeverContext):
    base = ctx.base
    keep_months = ctx.cfg.get_path("app.planning.idle_cash_buffer_months", 6)
    idle = base.cash - keep_months * base.spending_monthly
    if idle < 5000:
        return None
    years = ctx.months_to_target / 12
    portfolio = "conservative" if years < 3 else "balanced" if years < 10 else "growth"
    r, vol = ctx.cfg["market"]["portfolios"][portfolio].values()
    a = ctx.book("invest_idle_cash")
    amount = a.get("amount", round(idle, -3), label="Invest now", source="transactions", low=0, high=round(base.cash, -3), step=1000,
                   note=f"Cash above {keep_months} months of spending")
    fcf = ctx.profile.free_cash_flow_monthly - sum(ctx.profile.saving_contrib_monthly.values())
    monthly = a.get("monthly", max(0.0, round(0.5 * fcf, -2)), label="Monthly investment plan", source="transactions",
                    unit="CHF/month", low=0, high=max(0.0, round(fcf, -2)), step=50, note="Half of what you save each month today")
    r = a.get("expected_return", r, label=f"Expected return ({portfolio})", unit="%/yr", source="market_default",
              low=0.0, high=0.12, step=0.005)
    vol = a.get("volatility", vol, label=f"Volatility ({portfolio})", unit="%/yr", source="market_default",
                low=0.0, high=0.5, step=0.01)
    return LeverImpact(
        lever_id="invest_idle_cash", title="Put idle cash to work",
        description=f"Invest {fmt_chf(amount)} in a {portfolio} portfolio and {fmt_chf(monthly)}/month through a savings plan.",
        group="no_lifestyle_cost", effort="low", confidence="estimated", product_trigger="investment_plan", icon="trending-up",
        investments=[Investment(start=ctx.start, once=fixed(amount) if amount else None, monthly=fixed(monthly) if monthly > 0 else None,
                                expected_return=r, volatility=vol, label=f"{portfolio} portfolio")],
        headline_monthly=round((amount + monthly * min(ctx.months_to_target, 60) / 2) * (r - ctx.cfg["market"]["cash_rate"]) / 12),
        side_effects=[f"Value moves with markets: a bad year can be about -{2 * vol:.0%}"],
        assumptions=a.list(),
    )


@lever("max_3a")
def max_3a(ctx: LeverContext):
    limit = ctx.cfg.get_path("pension.pillar3a.max_with_pension_fund", 7258)
    room = limit - ctx.base.contrib_p3a_monthly * 12
    if room < 600 or ctx.base.age >= 64:
        return None
    a = ctx.book("max_3a")
    monthly = a.get("monthly", round(room / 12, 0), label="Pay into pillar 3a", unit="CHF/month", source="market_default",
                    low=0, high=round(room / 12), step=25, note=f"Legal maximum {fmt_chf(limit)}/year")
    rate = a.get("marginal_tax_rate", marginal_tax_rate(ctx.cfg, ctx.client.canton, ctx.profile.income.gross_annual * 0.8),
                 label="Your marginal tax rate (estimate)", unit="share", source="market_default", low=0.1, high=0.45, step=0.01,
                 needs_confirmation=True)
    lag = int(ctx.cfg.get_path("tax.tax_refund_lag_months", 8))
    tax_saving = monthly * rate
    return LeverImpact(
        lever_id="max_3a", title="Pay the maximum into pillar 3a",
        description=f"{fmt_chf(monthly * 12)}/year into 3a saves about {fmt_chf(tax_saving * 12)} in taxes each year.",
        group="no_lifestyle_cost", effort="low", confidence="structural", product_trigger="3a", icon="landmark",
        allocation_changes=[AllocationDelta(start=ctx.start, to_bucket="p3a", mode="monthly", amount=fixed(monthly), label="3a contributions")],
        recurring=[RecurringDelta(start=add_months(ctx.start, lag), monthly=fixed(tax_saving), label="Lower taxes")],
        side_effects=["3a money is locked until retirement, except for buying a home, emigrating or self-employment"],
        headline_monthly=round(tax_saving),
        assumptions=a.list(),
    )


@lever("cancel_subscriptions")
def cancel_subscriptions(ctx: LeverContext):
    out = []
    for r in ctx.profile.recurring:
        if not r.active or r.category != "subscriptions" or r.amount >= 0:
            continue
        lever_id = f"cancel:{slug(r.merchant)}"
        name = (r.counterparty or r.merchant).split(" International")[0].split(" AG")[0].split(" AB")[0].strip()
        a = ctx.book(lever_id)
        monthly = a.get("monthly", -r.monthly_equivalent, label=f"{name} per month", unit="CHF/month", source="transactions", step=1)
        out.append(LeverImpact(
            lever_id=lever_id, title=f"Cancel {name}", description=f"Saves {fmt_chf(monthly * 12)} a year.",
            group="behavioural", effort="low", confidence="structural", icon="x-circle",
            recurring=[RecurringDelta(start=ctx.start, monthly=fixed(monthly), category="subscriptions", label=f"No more {name}")],
            details={"title_args": {"name": name}}, assumptions=a.list(),
        ))
    return out


@lever("discretionary_cut")
def discretionary_cut(ctx: LeverContext):
    flows = [f for f in ctx.profile.flows if f.discretionary and f.category != "subscriptions" and f.monthly > 0]
    total = sum(f.monthly for f in flows)
    if total < 150:
        return None
    a = ctx.book("discretionary_cut")
    share = a.get("share", 0.15, label="Cut restaurants, shopping, leisure and travel by", unit="share", source="market_default",
                  low=0.05, high=0.4, step=0.05)
    monthly = share * total
    names = ", ".join(f.label.lower() for f in sorted(flows, key=lambda f: -f.monthly)[:3])
    return LeverImpact(
        lever_id="discretionary_cut", title=f"Spend {share:.0%} less on {names}",
        description=f"About {fmt_chf(monthly)}/month. Behavioural savings tend to fade; we count only part of them long-term.",
        group="behavioural", effort="medium", confidence="behavioural", icon="scissors",
        recurring=[RecurringDelta(start=ctx.start, monthly=fixed(monthly), behavioural=True, label="Lower discretionary spending")],
        details={"title_args": {"share": f"{share:.0%}"}}, assumptions=a.list(),
    )


@lever("use_pillar2", goal_types={"home"})
def use_pillar2(ctx: LeverContext):
    if ctx.goal.params.get("use_pillar2") or ctx.base.p2 < 20000 or ctx.base.age >= 60:
        return None
    price = float(ctx.goal.params.get("price", 0))
    m = ctx.cfg["mortgage"]
    pen = ctx.cfg["pension"]
    used = min(ctx.base.p2, price * (m["equity_min_share"] - m["hard_equity_min_share"]))
    years = max(0.0, 65 - ctx.base.age)
    lost_capital = used * (1 + pen["bvg"]["min_interest"]) ** years
    lost_pension = lost_capital * pen["bvg"]["conversion_rate"] / 12
    return LeverImpact(
        lever_id="use_pillar2", title="Use pension-fund money for the home",
        description=f"Withdraw about {fmt_chf(used)} from pillar 2 as equity (taxed at withdrawal).",
        group="structural", effort="medium", confidence="structural", product_trigger="mortgage", icon="building",
        goal_changes=[GoalChange(field="use_pillar2", op="set", value=1, label="Pillar 2 counts as equity")],
        side_effects=[f"Retirement: about {fmt_chf(lost_capital)} less pension capital, roughly {fmt_chf(lost_pension)}/month less pension",
                      "Pension-fund risk cover may shrink; can be repaid later"],
        assumptions=ctx.book("use_pillar2").list(),
    )


@lever("cheaper_home", goal_types={"home"})
def cheaper_home(ctx: LeverContext):
    a = ctx.book("cheaper_home")
    share = a.get("share", 0.15, label="Look for a home cheaper by", unit="share", source="market_default", low=0.05, high=0.4, step=0.05)
    price = float(ctx.goal.params.get("price", 0))
    return LeverImpact(
        lever_id="cheaper_home", title=f"Aim for a home {share:.0%} cheaper",
        description=f"About {fmt_chf(price * (1 - share))} instead of {fmt_chf(price)}: further out, older, or one room less.",
        group="goal_change", effort="medium", confidence="structural", icon="home",
        goal_changes=[GoalChange(field="price", op="mul", value=1 - share, label="Lower price")],
        details={"title_args": {"share": f"{share:.0%}"}}, assumptions=a.list(),
    )


@lever("smaller_target", goal_types={"target"})
def smaller_target(ctx: LeverContext):
    a = ctx.book("smaller_target")
    share = a.get("share", 0.2, label="Reduce the amount by", unit="share", source="market_default", low=0.05, high=0.5, step=0.05)
    amount = float(ctx.goal.params.get("amount", 0))
    return LeverImpact(
        lever_id="smaller_target", title=f"Plan for {share:.0%} less",
        description=f"{fmt_chf(amount * (1 - share))} instead of {fmt_chf(amount)}.",
        group="goal_change", effort="medium", confidence="structural", icon="target",
        goal_changes=[GoalChange(field="amount", op="mul", value=1 - share)],
        details={"title_args": {"share": f"{share:.0%}"}}, assumptions=a.list(),
    )


@lever("retire_later", goal_types={"retirement"})
def retire_later(ctx: LeverContext):
    a = ctx.book("retire_later")
    years = int(a.get("years", 2, label="Retire later by", unit="years", source="market_default", low=1, high=5, step=1))
    age = int(ctx.goal.params.get("retirement_age", 65))
    if age + years > 70:
        return None
    return LeverImpact(
        lever_id="retire_later", title=f"Retire at {age + years} instead of {age}",
        description="More years of saving and pension contributions, fewer years to finance.",
        group="goal_change", effort="high", confidence="structural", icon="target",
        goal_changes=[GoalChange(field="target_date", op="add_months", value=12 * years),
                      GoalChange(field="retirement_age", op="add", value=years)],
        details={"title_args": {"age": age + years, "from": age}}, assumptions=a.list(),
    )


@lever("lower_retirement_spending", goal_types={"retirement"})
def lower_retirement_spending(ctx: LeverContext):
    a = ctx.book("lower_retirement_spending")
    share = ctx.cfg.get_path("pension.retirement.default_spending_share", 0.8)
    current = float(ctx.goal.params.get("spending_monthly") or ctx.base.spending_monthly * share)
    cut = a.get("share", 0.1, label="Plan to spend less in retirement by", unit="share", source="market_default", low=0.05,
                high=0.3, step=0.05)
    return LeverImpact(
        lever_id="lower_retirement_spending", title=f"Plan retirement on {fmt_chf(current * (1 - cut))}/month",
        description=f"Instead of {fmt_chf(current)}/month (today's money): e.g. a smaller home or fewer trips.",
        group="goal_change", effort="medium", confidence="structural", icon="target",
        goal_changes=[GoalChange(field="spending_monthly", op="set", value=current * (1 - cut))],
        details={"title_args": {"amount": fmt_chf(current * (1 - cut))}}, assumptions=a.list(),
    )
