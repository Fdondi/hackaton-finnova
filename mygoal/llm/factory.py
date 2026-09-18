from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import httpx

from ..config import Config
from .base import LLMClient


def _anthropic_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return (Path.home() / ".config" / "anthropic").exists()   # `ant auth login` profile


def _local_endpoint(base_url: str) -> bool:
    try:
        return httpx.get(base_url.rstrip("/") + "/models", timeout=0.7).status_code == 200
    except httpx.HTTPError:
        return False


@lru_cache(maxsize=1)
def _build(provider: str, agent_model: str, fast_model: str, base_url: str, local_model: str,
           api_model: str, api_reasoning_effort: str | None) -> LLMClient | None:
    if provider in ("anthropic", "auto") and (provider == "anthropic" or _anthropic_credentials()):
        try:
            from .anthropic_client import AnthropicClient
            return AnthropicClient(agent_model, fast_model)
        except Exception:
            if provider == "anthropic":
                raise
    api_key = os.environ.get("OPENAI_API_KEY")
    if provider in ("openai", "auto") and (provider == "openai" or api_key):
        from .openai_compat import OpenAICompatClient
        # gpt-5.x on chat completions only accepts function tools with reasoning_effort "none"
        params = {"reasoning_effort": api_reasoning_effort} if api_reasoning_effort else {}
        return OpenAICompatClient("https://api.openai.com/v1", api_model, api_key=api_key, name="openai",
                                  token_param="max_completion_tokens", params=params)
    if provider in ("openai_compat", "auto") and (provider == "openai_compat" or _local_endpoint(base_url)):
        from .openai_compat import OpenAICompatClient
        return OpenAICompatClient(base_url, local_model)
    return None


def get_llm(cfg: Config) -> LLMClient | None:
    llm = cfg.get_path("app.llm", {})
    if llm.get("provider") == "none":
        return None
    return _build(llm.get("provider", "auto"), llm.get("agent_model"), llm.get("fast_model"),
                  llm.get("openai_base_url"), llm.get("openai_model"), llm.get("openai_api_model"),
                  llm.get("openai_api_reasoning_effort"))


def llm_status(cfg: Config) -> dict:
    client = get_llm(cfg)
    return {"available": client is not None, "provider": getattr(client, "name", None), "model": getattr(client, "model", None)}
