"""Life events calibrated on the bank's population data: "what actually happened to people like you".

Each lever only exists when the population service has enough cases (mygoal/population.py, n >= 20); every number
carries the `population` source and the number of people behind it. Without population data they return None.
"""
from __future__ import annotations

from ..levers import LeverContext, lever
from ..model import IncomeDelta, LeverImpact, OneOff, add_months, empirical, triangular
from ..swiss import fmt_chf


def evidence(ctx: LeverContext, name: str) -> dict | None:
    pop = ctx.services.get("population")
    return pop.life_event(name) if pop is not None else None


def _married(ctx: LeverContext) -> bool:
    return ctx.client.extra.get("marital_status") == "married" or ctx.client.household.adults >= 2


@lever("wedding", kind="life_event", origin="specialist")
def wedding(ctx: LeverContext):
    ev = evidence(ctx, "marriage")
    if not ev or _married(ctx) or not (20 <= ctx.base.age <= 55) or not ev.get("event_costs", {}).get("median_if_any"):
        return None
    c = ev["event_costs"]
    a = ctx.book("wedding")
    in_months = int(a.get("in_months", 12, label="Wedding in", unit="months", source="market_default", low=0, high=60, step=1,
                         needs_confirmation=True))
    cost = a.get("cost", c["median_if_any"], label="Wedding costs", unit="CHF", source="population",
                 low=c["iqr_if_any"][0], high=c["iqr_if_any"][1], step=1000,
                 note=f"Median of {c['n_events']} weddings in the bank's data ({c['share_with_costs']:.0%} had costs; "
                      f"middle half {fmt_chf(c['iqr_if_any'][0])}-{fmt_chf(c['iqr_if_any'][1])})")
    when = add_months(ctx.start, in_months)
    return LeverImpact(
        lever_id="wedding", title="Get married",
        description=f"Weddings in the bank's data cost a median {fmt_chf(cost)}; monthly spending barely changed afterwards "
                    f"({ev['n']} people).",
        group="life_event", effort="high", confidence="estimated", icon="heart",
        one_offs=[OneOff(at=when, amount=triangular(-c["iqr_if_any"][1], -cost, -c["iqr_if_any"][0]), label="Wedding")],
        assumptions=a.list(),
    )


@lever("separation", kind="life_event", origin="specialist")
def separation(ctx: LeverContext):
    ev = evidence(ctx, "divorce")
    if not ev or not _married(ctx) or not ev.get("event_costs", {}).get("median_if_any"):
        return None
    c = ev["event_costs"]
    a = ctx.book("separation")
    in_months = int(a.get("in_months", 12, label="Separation in", unit="months", source="market_default", low=0, high=60,
                         step=1, needs_confirmation=True))
    cap = 0.6 * max(ctx.base.cash + ctx.base.invested, 0.0)   # the asset split scales with what there is to split
    cost = a.get("cost", min(c["median_if_any"], cap) if cap else c["median_if_any"], label="Asset split and lawyers",
                 unit="CHF", source="population", low=0, high=max(c["iqr_if_any"][1], cap), step=1000,
                 note=f"Median {fmt_chf(c['median_if_any'])} in {c['n_events']} separations in the bank's data "
                      f"(asset split, lawyers), capped at 60% of your savings")
    when = add_months(ctx.start, in_months)
    return LeverImpact(
        lever_id="separation", title="Separation",
        description=f"In the bank's data, separations cost a median {fmt_chf(c['median_if_any'])} in the month "
                    f"(asset split, lawyers); for you about {fmt_chf(cost)}.",
        group="life_event", effort="high", confidence="estimated", icon="split",
        one_offs=[OneOff(at=when, amount=triangular(-1.3 * cost, -cost, -0.8 * cost), label="Asset split and lawyers")],
        side_effects=["Housing for two households is not modelled yet"],
        assumptions=a.list(),
    )


@lever("job_change", kind="life_event", origin="specialist")
def job_change(ctx: LeverContext):
    ev = evidence(ctx, "job_change")
    r = (ev or {}).get("income_ratio") or {}
    if not r.get("ratio_quantiles") or ctx.base.salary_net_monthly <= 0 or ctx.base.age >= 63:
        return None
    a = ctx.book("job_change")
    in_months = int(a.get("in_months", 6, label="New job in", unit="months", source="market_default", low=0, high=60, step=1,
                         needs_confirmation=True))
    salary = ctx.base.salary_net_monthly
    change = [salary * (q - 1) for q in r["ratio_quantiles"]]           # each future draws one real outcome
    when = add_months(ctx.start, in_months)
    return LeverImpact(
        lever_id="job_change", title="Change jobs",
        description=f"Of {r['n']} job changes in the bank's data, the median salary went up {r['median_change_pct']:+.0%}, "
                    f"but {r['share_cut']:.0%} took a pay cut (typically {r['cut_median_pct']:+.0%}). Each future draws one "
                    f"of these outcomes.",
        group="life_event", effort="high", confidence="estimated", icon="briefcase",
        income_changes=[IncomeDelta(start=when, monthly_net=empirical(change), affects_gross=False,
                                    label="Salary after the job change")],
        assumptions=a.list(),
    )
