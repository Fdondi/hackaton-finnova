from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class GoalSpec(BaseModel):
    """A client goal. `type` selects a goal plugin (mygoal/goals); `params` is validated by it.

    Keeping params as a dict means a new goal type never touches this model.
    """
    id: str
    type: str                      # home | target | retirement | ...
    label: str
    target_date: date | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = 1
