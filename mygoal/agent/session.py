from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field


class WhatIfQuestion(BaseModel):
    id: str
    text: str
    kind: Literal["number", "choice", "text"] = "number"
    unit: str | None = None
    options: list[str] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    default: float | str | None = None


class WhatIfStep(BaseModel):
    kind: Literal["tool", "note"] = "tool"
    name: str
    summary: str


class WhatIfResult(BaseModel):
    session_id: str
    status: Literal["question", "lever", "existing_lever", "unsupported", "error"]
    agent: Literal["llm", "rules", "specialist", "none"]
    message: str = ""
    question: WhatIfQuestion | None = None
    lever_id: str | None = None
    steps: list[WhatIfStep] = Field(default_factory=list)
    evaluation: dict[str, Any] | None = None


@dataclass
class Session:
    client_id: str
    goal_id: str
    text: str
    lang: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    agent: str = "none"
    steps: list[WhatIfStep] = field(default_factory=list)
    questions: int = 0
    tool_calls: int = 0
    lever_id: str | None = None
    state: dict[str, Any] = field(default_factory=dict)   # agent-specific (conversation, pending call, answers)
