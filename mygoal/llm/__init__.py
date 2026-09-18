"""Provider-neutral LLM access. The LLM routes, asks, phrases and proposes labelled estimates; it never computes.

    get_llm(cfg) -> LLMClient | None   (None = run without an LLM; every feature has a fallback)
"""
from .base import Conversation, LLMClient, LLMTurn, ToolCall, ToolSpec
from .factory import get_llm, llm_status

__all__ = ["Conversation", "LLMClient", "LLMTurn", "ToolCall", "ToolSpec", "get_llm", "llm_status"]
