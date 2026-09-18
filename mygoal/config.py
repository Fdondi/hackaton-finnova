"""Loads config/*.yaml into one dict-like object.

Every file in the config directory becomes a top-level key (market.yaml -> cfg["market"]).
A handful of env vars override app settings so containers need no file edits.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # local dev convenience; real env vars (containers, CI) always win

CONFIG_DIR = Path(os.environ.get("MYGOAL_CONFIG_DIR", ROOT / "config"))

_ENV_OVERRIDES = {
    "LLM_PROVIDER": ("app", "llm", "provider"),
    "OPENAI_BASE_URL": ("app", "llm", "openai_base_url"),
    "OPENAI_MODEL": ("app", "llm", "openai_model"),
    "OPENAI_API_MODEL": ("app", "llm", "openai_api_model"),
    "OPENAI_REASONING_EFFORT": ("app", "llm", "openai_api_reasoning_effort"),
    "MYGOAL_AGENT_MODEL": ("app", "llm", "agent_model"),
    "MYGOAL_DATA_SOURCE": ("app", "data", "source"),
    "MYGOAL_DATA_DIR": ("app", "data", "dir"),
    "MYGOAL_N_PATHS": ("app", "simulation", "n_paths"),
}


class Config(dict):
    """A dict with dotted-path access: cfg.get_path("market.cash_rate")."""

    def get_path(self, path: str, default: Any = None) -> Any:
        node: Any = self
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def by_canton(self, path: str, canton: str | None, default: Any = None) -> Any:
        """Look up a {default: x, ZH: y} style table."""
        table = self.get_path(path, {})
        if not isinstance(table, dict):
            return table
        return table.get(canton or "", table.get("default", default))

    def by_age(self, path: str, age: int, key: str = "max_age") -> dict:
        """Pick the first row of a [{max_age: .., ...}] table that covers `age`."""
        rows = self.get_path(path, [])
        for row in rows:
            if age <= row[key]:
                return row
        return rows[-1]


def _coerce(value: str) -> Any:
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


@lru_cache(maxsize=1)
def load_config() -> Config:
    cfg = Config()
    for path in sorted(CONFIG_DIR.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            cfg[path.stem] = yaml.safe_load(fh) or {}
    for env, keys in _ENV_OVERRIDES.items():
        if env in os.environ:
            node = cfg
            for k in keys[:-1]:
                node = node.setdefault(k, {})
            node[keys[-1]] = _coerce(os.environ[env])
    return cfg


def resolve_path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p
