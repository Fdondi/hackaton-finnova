"""Family isn't a savings goal, it's a bundle of levers: leave, childcare, costs, allowances, space, part-time."""
from __future__ import annotations

from ..levers import LeverContext, lever
from ..model import IncomeDelta, LeverImpact, RecurringDelta, add_months, fixed
from ..swiss import fmt_chf


@lever("have_child", kind="life_event", origin="specialist")
def have_child(ctx: LeverContext):
    if ctx.base.age > 48:
        return None
    fam = ctx.cfg["family"]
    couple = ctx.client.household.adults >= 2
    siblings = len(ctx.client.household.children_birth_years)
    a = ctx.book("have_child")
    in_months = int(a.get("in_months", 12, label="Baby expected in", unit="months", source="market_default", low=0, high=60,
                          step=1, needs_confirmation=True))
    share = a.get("leave_income_share", 0.35 if couple else 1.0, label="Share of household salary from the parent taking leave",
                  unit="share", source="market_default", low=0.0, high=1.0, step=0.05, needs_confirmation=True)
    unpaid = int(a.get("unpaid_months", fam["maternity"]["unpaid_extra_months"], label="Unpaid leave after maternity leave",
                       unit="months", source="market_default", low=0, high=12, step=1))
    work_after = a.get("work_share_after", 0.8 if couple and not siblings else 1.0, label="Work percentage afterwards", unit="share",
                       source="market_default", low=0.0, high=1.0, step=0.1, needs_confirmation=True)
    days = a.get("childcare_days", fam["childcare"]["days_per_week"], label="Daycare days per week", unit="days", source="market_default",
                 low=0, high=5, step=1)
    canton = ctx.client.canton
    allowance = ctx.cfg.by_canton("family.child_allowance_monthly", canton, 215)
    care = days * fam["childcare"]["daycare_full_day"] * 52 / 12 * (1 - fam["childcare"]["subsidy_share"])
    birth = add_months(ctx.start, in_months)
    leave_end = add_months(birth, 3 + unpaid)
    care_start = add_months(birth, fam["childcare"]["start_after_months"])
    kinder = add_months(birth, 12 * fam["childcare"]["until_age_years"])
    scale = 0.7 if siblings else 1.0   # economies of scale for further children (estimate)
    extra_room = a.get("extra_housing_monthly", 0 if siblings else fam["extra_housing_monthly"], label="Extra rent for more space",
                       unit="CHF/month", source="market_default", low=0, high=1200, step=50, needs_confirmation=True)
    running = fam["child_costs_monthly"] * scale + fam["child_health_premium_monthly"] + extra_room - allowance
    return LeverImpact(
        lever_id="have_child", title="Have a child" if not ctx.client.household.children_birth_years else "Have another child",
        description=f"From month {in_months}: about {fmt_chf(running)}/month running costs after allowances, "
                    f"{fmt_chf(care)}/month daycare for {days:.0f} days a week, and less income during leave.",
        group="life_event", effort="high", confidence="estimated", icon="baby",
        income_changes=[
            IncomeDelta(start=birth, end=add_months(birth, 2), salary_factor=1 - share * (1 - fam["maternity"]["replacement"]), label="Maternity leave (80%)"),
            *([IncomeDelta(start=add_months(birth, 3), end=add_months(leave_end, -1), salary_factor=1 - share, label="Unpaid leave")] if unpaid else []),
            *([IncomeDelta(start=leave_end, salary_factor=1 - share * (1 - work_after), label="Part-time afterwards")] if work_after < 1 else []),
        ],
        recurring=[
            RecurringDelta(start=birth, monthly=fixed(-running), label="Child costs, premium and space minus allowance"),
            RecurringDelta(start=care_start, end=add_months(kinder, -1), monthly=fixed(-care), label="Daycare"),
            RecurringDelta(start=kinder, end=add_months(birth, 12 * 12), monthly=fixed(-0.4 * care), label="After-school care"),
        ],
        side_effects=["Also lowers taxes (child deductions) - not modelled yet"],
        assumptions=a.list(),
    )
