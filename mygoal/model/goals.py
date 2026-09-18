from __future__ import annotations

from datetime import date
from typing import Any, Literal

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
    status: Literal["suggested", "confirmed"] = "confirmed"   # suggestions wait for the client's OK on the goals page
    origin: Literal["data", "ai", "user"] = "user"            # rules on the bank's data, the LLM, or the client
    note: str | None = None                                    # why it was suggested / how the amount was estimated
    i18n: dict[str, dict[str, str]] = Field(default_factory=dict)   # lang -> {"label", "note"} for AI suggestions
    category: str | None = None        # home, car, travel, education, hobby, collection, business, family, safety, ...
