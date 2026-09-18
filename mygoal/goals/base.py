"""Goal plugins. A goal says, for every simulated month and path: is it achievable now, what do I have,
what would I need. Everything else (success probability, dates, gap, deadline) is generic.

Add a goal type: write a module with a class decorated @register_goal("type") implementing GoalPlugin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import ClassVar, Protocol

import numpy as np
from pydantic import BaseModel

from ..config import Config
from ..engine import Baseline, Trajectories
from ..model import GoalSpec, LeverImpact, add_months
from ..registry import Registry


@dataclass
class GoalEval:
    feasible: np.ndarray            # (T+1, N) bool
    have: np.ndarray                # (T+1, N) what counts toward the goal (CHF)
    need: np.ndarray                # (T+1, N) what the goal requires (CHF)
    constraints: dict[str, np.ndarray] = field(default_factory=dict)  # name -> (T+1, N) bool "this constraint holds"
    have_label: str = "own funds"
    need_label: str = "required"


class GoalPlugin(Protocol):
    type: ClassVar[str]
    Params: ClassVar[type[BaseModel]]

    def evaluate(self, spec: GoalSpec, params: BaseModel, traj: Trajectories, base: Baseline, cfg: Config) -> GoalEval: ...

    def commitment(self, spec: GoalSpec, params: BaseModel, base: Baseline, cfg: Config, at: date) -> LeverImpact | None:
        """What achieving this goal at `at` does to the household (used to show effects on other goals)."""
        ...

    def default_target(self, spec: GoalSpec, base: Baseline) -> date | None: ...

    def horizon_end(self, spec: GoalSpec, params: BaseModel, base: Baseline) -> date | None:
        """Last month worth simulating (None: target date + app.simulation.horizon_years_after_target)."""
        ...


GOALS: Registry[GoalPlugin] = Registry("goals")


def register_goal(type_name: str):
    def wrap(cls):
        cls.type = type_name
        GOALS.register(type_name, cls())
        return cls
    return wrap


def parse_params(plugin: GoalPlugin, spec: GoalSpec) -> BaseModel:
    return plugin.Params.model_validate(spec.params)


def target_date(plugin: GoalPlugin, spec: GoalSpec, base: Baseline) -> date:
    return spec.target_date or plugin.default_target(spec, base) or add_months(base.start, 60)
