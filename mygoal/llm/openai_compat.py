"""Any OpenAI Chat Completions API: a local server (LM Studio, vLLM, llama.cpp) or the real OpenAI cloud API.

Local is the "client data never leaves the bank" option: same agent, a Swiss-hosted or on-prem model behind it.
Cloud OpenAI is a cheaper stand-in for Claude's fast model (see factory.py's "openai" provider).
"""
from __future__ import annotations

import json

from .base import LLMTurn, ToolCall, ToolSpec


class OpenAICompatConversation:
    def __init__(self, client, model: str, system: str, tools: list[ToolSpec], params: dict):
        self.client, self.model, self.params = client, model, params
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
                      for t in tools]
        self.messages: list[dict] = [{"role": "system", "content": system}]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        for cid, content, err in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": ("ERROR: " if err else "") + content})

    def step(self) -> LLMTurn:
        try:
            r = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tools,
                                                    **self.params)
        except Exception as exc:  # local servers raise a variety of errors
            return LLMTurn(text=f"LLM error: {exc}", stop_reason="error")
        msg = r.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))
        self.messages.append({"role": "assistant", "content": msg.content or "",
                              **({"tool_calls": [tc.model_dump() for tc in msg.tool_calls]} if msg.tool_calls else {})})
        return LLMTurn(text=msg.content or "", tool_calls=calls, stop_reason="tool_use" if calls else "end_turn")


class OpenAICompatClient:
    # OpenAI cloud (gpt-5.x, o-series) rejects max_tokens and wants max_completion_tokens; many local servers
    # only know max_tokens. `params` go into every request (e.g. reasoning_effort, see factory.py).
    def __init__(self, base_url: str, model: str, api_key: str = "not-needed", name: str = "openai_compat",
                 max_tokens: int = 4000, token_param: str = "max_tokens", params: dict | None = None):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model, self.max_tokens, self.name, self.token_param = model, max_tokens, name, token_param
        self.params = params or {}

    def conversation(self, system: str, tools: list[ToolSpec]) -> OpenAICompatConversation:
        return OpenAICompatConversation(self.client, self.model, system, tools,
                                        {self.token_param: self.max_tokens, **self.params})

    def complete(self, system: str, prompt: str, max_tokens: int = 4000) -> str:
        r = self.client.chat.completions.create(model=self.model, **{self.token_param: max_tokens, **self.params},
                                                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}])
        return r.choices[0].message.content or ""
