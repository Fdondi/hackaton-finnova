"""Lever registry and context.

A lever builder gets a LeverContext and returns a LeverImpact (or a list, or None if it doesn't apply):

    @lever("cancel_netflix", goal_types=None)
    def build(ctx: LeverContext):
        a = ctx.book("cancel_netflix")
        saving = a.get("monthly", 20.9, label="Netflix per month", source="transactions")
        return LeverImpact(lever_id="cancel_netflix", title="Cancel Netflix", assumptions=a.list(),
                           recurring=[RecurringDelta(start=ctx.start, monthly=fixed(saving))])

`ctx.book(lever_id)` applies the user's edits from the "Why?" drawer automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

from ..config import Config
from ..engine import Baseline
from ..model import AssumptionBook, Client, GoalSpec, LeverImpact, months_between
from ..profile import Profile
from ..registry import Registry


@dataclass
class LeverContext:
    client: Client
    profile: Profile
    base: Baseline
    goal: GoalSpec
    cfg: Config
    overrides: dict[str, dict[str, float]] = field(default_factory=dict)
    services: dict[str, Any] = field(default_factory=dict)
    target: date | None = None

    def book(self, lever_id: str) -> AssumptionBook:
        return AssumptionBook(self.overrides.get(lever_id))

    @property
    def start(self) -> date:
        return self.base.start

    @property
    def months_to_target(self) -> int:
        return max(1, months_between(self.base.start, self.target)) if self.target else 60


Builder = Callable[[LeverContext], LeverImpact | list[LeverImpact] | None]


@dataclass
class LeverDef:
    id: str
    build: Builder
    goal_types: set[str] | None = None
    kind: Literal["option", "life_event"] = "option"
    origin: Literal["builtin", "specialist"] = "builtin"


LEVERS: Registry[LeverDef] = Registry("levers")


def lever(lever_id: str, goal_types: set[str] | list[str] | None = None, kind: str = "option", origin: str = "builtin"):
    def wrap(fn: Builder) -> Builder:
        LEVERS.register(lever_id, LeverDef(lever_id, fn, set(goal_types) if goal_types else None, kind, origin))
        return fn
    return wrap


def build_levers(ctx: LeverContext) -> list[LeverImpact]:
    out: list[LeverImpact] = []
    for d in LEVERS.values():
        if d.goal_types and ctx.goal.type not in d.goal_types:
            continue
        result = d.build(ctx)
        for impact in (result if isinstance(result, list) else [result] if result else []):
            if d.kind == "life_event":
                impact.group = "life_event"
            if impact.origin == "builtin" and d.origin == "specialist":
                impact.origin = "specialist"
            out.append(impact)
    return out
