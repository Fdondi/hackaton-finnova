"""Buying a home in Switzerland: two gates plus saving up.

Equity: >= 20% of the price, of which >= 10 points "hard" (not pillar 2), plus buying costs in cash.
Affordability: (imputed interest 5% + maintenance 1% + amortisation of the 2nd mortgage) / gross income <= 1/3.
More equity lowers the mortgage, so saving helps with both gates.
"""
from __future__ import annotations

from datetime import date

import numpy as np
from pydantic import BaseModel

from ..model import GoalSpec, LeverImpact, RecurringDelta, Withdrawal, fixed
from .base import GoalEval, register_goal


class HomeParams(BaseModel):
    price: float                     # today's CHF
    canton: str | None = None
    use_pillar2: bool = False
    use_pillar3a: bool = True


def max_mortgage(price, gross, m: dict, years_to_amortise: float):
    """Largest mortgage passing the affordability test (vectorised)."""
    r, maint, ratio = m["imputed_interest_rate"], m["maintenance_rate"], m["max_cost_to_income"]
    a = m["second_mortgage_to_ltv"]
    n = max(years_to_amortise, 1.0)
    budget = ratio * gross - maint * price
    m1 = np.minimum(budget / r, a * price)              # no second mortgage
    m2 = (budget + a * price / n) / (r + 1 / n)         # with a second mortgage amortised over n years
    return np.where(m2 > a * price, m2, m1)


@register_goal("home")
class HomeGoal:
    Params = HomeParams

    def _rules(self, cfg, params: HomeParams, base):
        m = cfg["mortgage"]
        costs = cfg.by_canton("mortgage.buying_costs_share", params.canton or base.canton, 0.03)
        return m, costs

    def evaluate(self, spec, params: HomeParams, traj, base, cfg) -> GoalEval:
        m, cost_share = self._rules(cfg, params, base)
        price = params.price * traj.house
        hard = np.maximum(traj.cash - base.buffer_reserve * traj.price, 0.0) + traj.invested \
            + (traj.p3a if params.use_pillar3a and m.get("pillar3a_counts_as_hard_equity", True) else 0.0)
        p2 = np.maximum(traj.p2, 0.0) * (1 - m.get("pillar2_withdrawal_tax_rate", 0.0)) if params.use_pillar2 else np.zeros_like(traj.p2)
        years_left = max(65 - base.age, 1)
        mortgage_max = max_mortgage(price, traj.gross, m, min(m["amortisation_years"], years_left))
        equity_needed = np.maximum(m["equity_min_share"] * price, price - mortgage_max)
        costs = cost_share * price
        hard_ok = hard >= m["hard_equity_min_share"] * price + costs
        total_ok = hard + p2 >= equity_needed + costs
        afford_ok = mortgage_max > 0
        feasible = hard_ok & total_ok & afford_ok
        return GoalEval(
            feasible=feasible, have=hard + p2, need=np.maximum(equity_needed, 0) + costs,
            constraints={"hard_equity": hard_ok, "total_equity": total_ok, "affordability": afford_ok},
            have_label="own funds for the home", need_label="equity the bank requires",
        )

    def commitment(self, spec, params: HomeParams, base, cfg, at: date) -> LeverImpact:
        """Buy at `at`: pay the equity, stop paying rent, start paying interest + maintenance + amortisation."""
        m, cost_share = self._rules(cfg, params, base)
        price = params.price
        mortgage = max(0.0, min(0.8 * price, float(max_mortgage(price, base.gross_income_annual, m, m["amortisation_years"]))))
        equity = price - mortgage + cost_share * price
        order = ["cash", "invested", "p3a"] + (["p2"] if params.use_pillar2 else [])
        second = max(0.0, mortgage - m["second_mortgage_to_ltv"] * price)
        monthly_owner = (mortgage * m["actual_mortgage_rate"] + price * m["maintenance_rate"] + second / m["amortisation_years"]) / 12
        caps = {"cash": float("inf")}
        if params.use_pillar2:
            caps["p2"] = price * (m["equity_min_share"] - m["hard_equity_min_share"])
        return LeverImpact(
            lever_id=f"goal:{spec.id}", title=spec.label, group="life_event",
            withdrawals=[Withdrawal(at=at, amount=fixed(equity), order=order, caps={k: v for k, v in caps.items() if v != float("inf")},
                                    house_indexed=True, label="Equity and buying costs")],
            recurring=[RecurringDelta(start=at, monthly=fixed(base.housing_monthly - monthly_owner), label="Rent replaced by owner costs")],
        )

    def default_target(self, spec: GoalSpec, base) -> date | None:
        return None
