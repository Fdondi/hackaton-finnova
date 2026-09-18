from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"      # end_turn | tool_use | max_tokens | refusal | error


class Conversation(Protocol):
    """Provider-native message history; callers only see neutral turns and tool calls."""

    def add_user(self, text: str) -> None: ...
    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None: ...   # (call id, content, is_error)
    def step(self) -> LLMTurn: ...


class LLMClient(Protocol):
    name: str
    model: str

    def conversation(self, system: str, tools: list[ToolSpec]) -> Conversation: ...
    def complete(self, system: str, prompt: str, max_tokens: int = 4000) -> str: ...
