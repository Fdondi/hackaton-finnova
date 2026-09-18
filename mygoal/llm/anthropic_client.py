"""Claude via the official Anthropic SDK (manual tool loop: the agent pauses across HTTP requests to ask the user)."""
from __future__ import annotations

import anthropic

from .base import LLMTurn, ToolCall, ToolSpec


class AnthropicConversation:
    def __init__(self, client: anthropic.Anthropic, model: str, system: str, tools: list[ToolSpec], max_tokens: int):
        self.client, self.model, self.system, self.max_tokens = client, model, system, max_tokens
        self.tools = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        # all results of one assistant turn go back in a single user message
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": cid, "content": content, **({"is_error": True} if err else {})}
            for cid, content, err in results
        ]})

    def step(self) -> LLMTurn:
        try:
            response = self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens, system=self.system, tools=self.tools, messages=self.messages,
            )
        except anthropic.APIStatusError as exc:
            return LLMTurn(text=f"LLM error {exc.status_code}: {exc.message}", stop_reason="error")
        except anthropic.APIConnectionError as exc:
            return LLMTurn(text=f"LLM connection error: {exc}", stop_reason="error")
        # keep the full content (thinking + tool_use blocks) so the next request is valid
        self.messages.append({"role": "assistant", "content": response.content})
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [ToolCall(id=b.id, name=b.name, input=dict(b.input)) for b in response.content if b.type == "tool_use"]
        return LLMTurn(text=text, tool_calls=calls, stop_reason=response.stop_reason or "end_turn")


class AnthropicClient:
    name = "anthropic"

    def __init__(self, model: str, fast_model: str, max_tokens: int = 16000):
        self.client = anthropic.Anthropic()
        self.model, self.fast_model, self.max_tokens = model, fast_model, max_tokens

    def conversation(self, system: str, tools: list[ToolSpec]) -> AnthropicConversation:
        return AnthropicConversation(self.client, self.model, system, tools, self.max_tokens)

    def complete(self, system: str, prompt: str, max_tokens: int = 4000) -> str:
        response = self.client.messages.create(
            model=self.fast_model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in response.content if b.type == "text")
