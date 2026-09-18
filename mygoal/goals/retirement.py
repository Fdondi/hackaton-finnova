"""Retirement (simplified): can private savings fill the gap between retirement spending and pensions?

Pensions: AHV (scaled by income, reduced when drawn early, 13th payment) + pension-fund annuity
(pillar 2 capital x conversion rate, lower when retiring early). Private capital (cash above the
reserve, investments, 3a) must cover the remaining gap until life expectancy, including a bridge
without AHV if retiring before the earliest AHV age. P1 quality: good for "how does buying a home
with pillar 2 move my retirement?", not for a pension statement.
"""
from __future__ import annotations

from datetime import date

import numpy as np
from pydantic import BaseModel

from ..model import GoalSpec, IncomeDelta, LeverImpact
from .base import GoalEval, register_goal


class RetirementParams(BaseModel):
    retirement_age: int = 65
    spending_monthly: float | None = None      # today's CHF; default: share of today's spending
    earliest_age: int = 58


def _annuity(years, r):
    years = np.maximum(years, 0.0)
    return years if r == 0 else (1 - (1 + r) ** (-years)) / r


def ahv_monthly(cfg, gross: float) -> float:
    a = cfg["pension"]["ahv"]
    lo = a["income_for_max"] / 6
    share = np.clip((gross - lo) / (a["income_for_max"] - lo), 0, 1)
    return a["min_monthly"] + share * (a["max_monthly"] - a["min_monthly"])


@register_goal("retirement")
class RetirementGoal:
    Params = RetirementParams

    def spending(self, params: RetirementParams, base, cfg) -> float:
        if params.spending_monthly:
            return params.spending_monthly
        return base.spending_monthly * cfg.get_path("pension.retirement.default_spending_share", 0.8)

    def evaluate(self, spec, params: RetirementParams, traj, base, cfg) -> GoalEval:
        pen = cfg["pension"]
        ahv_cfg, bvg = pen["ahv"], pen["bvg"]
        life = pen["retirement"]["life_expectancy_age"]
        r = pen["retirement"]["real_return_in_retirement"]
        ages = np.array([base.age_at(traj.date_at(i)) for i in range(traj.T + 1)])[:, None]
        spend = self.spending(params, base, cfg) * traj.price * 12
        thirteenth = 13 / 12
        ahv_start = np.maximum(ages, ahv_cfg["earliest_age"])
        ahv_reduction = np.clip((ahv_cfg["reference_age"] - ahv_start) * ahv_cfg["early_reduction_per_year"], 0, 1)
        ahv = ahv_monthly(cfg, base.gross_income_annual) * thirteenth * 12 * (1 - ahv_reduction) * traj.price
        conv = bvg["conversion_rate"] - np.clip(ahv_cfg["reference_age"] - ages, 0, None) * bvg["early_conversion_reduction_per_year"]
        bvg_annuity = np.maximum(traj.p2, 0) * conv
        bridge_years = np.clip(ahv_start - ages, 0, None)
        later_years = np.clip(life - ahv_start, 0, None)
        need = (np.maximum(spend - bvg_annuity, 0) * _annuity(bridge_years, r)
                + np.maximum(spend - bvg_annuity - ahv, 0) * _annuity(later_years, r) * (1 + r) ** (-bridge_years))
        have = np.maximum(traj.cash - base.buffer_reserve * traj.price, 0) + traj.invested + traj.p3a
        old_enough = np.broadcast_to(ages >= params.earliest_age, have.shape)
        return GoalEval(feasible=old_enough & (have >= need), have=np.asarray(have), need=np.asarray(need),
                        constraints={"capital": have >= need, "age": old_enough},
                        have_label="private savings", need_label="capital needed to fill the pension gap")

    def commitment(self, spec, params: RetirementParams, base, cfg, at: date) -> LeverImpact:
        return LeverImpact(lever_id=f"goal:{spec.id}", title=spec.label, group="life_event",
                           income_changes=[IncomeDelta(start=at, salary_factor=0.0, label="Stop working")])

    def default_target(self, spec: GoalSpec, base) -> date | None:
        params = RetirementParams.model_validate(spec.params)
        if base.birth_year:
            return date(base.birth_year + params.retirement_age, 1, 1)
        return None

    def horizon_end(self, spec, params: RetirementParams, base) -> date | None:
        if base.birth_year:
            return date(base.birth_year + 70, 12, 1)
        return None
