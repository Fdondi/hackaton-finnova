"""Amount by a date: a trip, a sabbatical, a wedding, a car."""
from __future__ import annotations

from datetime import date

import numpy as np
from pydantic import BaseModel

from ..model import GoalSpec, LeverImpact, OneOff, fixed
from .base import GoalEval, register_goal


class TargetParams(BaseModel):
    amount: float                    # today's CHF
    include_invested: bool = True


@register_goal("target")
class TargetGoal:
    Params = TargetParams

    def evaluate(self, spec, params: TargetParams, traj, base, cfg) -> GoalEval:
        have = traj.cash - base.buffer_reserve * traj.price + (traj.invested if params.include_invested else 0.0)
        need = params.amount * traj.price
        return GoalEval(feasible=have >= need, have=np.asarray(have), need=np.asarray(need),
                        constraints={"savings": have >= need}, have_label="savings available", need_label="goal amount")

    def commitment(self, spec, params: TargetParams, base, cfg, at: date) -> LeverImpact:
        return LeverImpact(lever_id=f"goal:{spec.id}", title=spec.label, group="life_event",
                           one_offs=[OneOff(at=at, amount=fixed(-params.amount), label=spec.label)])

    def default_target(self, spec: GoalSpec, base) -> date | None:
        return None
