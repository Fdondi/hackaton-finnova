"""Templated explanations. Numbers come from the engine; wording comes from i18n/<lang>.yaml.
(An LLM may rephrase these later; it never produces the numbers.)"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).parent / "i18n"
LANGS = ("en", "de")


@lru_cache(maxsize=4)
def strings(lang: str) -> dict:
    lang = lang if lang in LANGS else "en"
    return yaml.safe_load((HERE / f"{lang}.yaml").read_text(encoding="utf-8"))


def t(key: str, lang: str = "en", default: str | None = None, **kw) -> str:
    node = strings(lang)
    for part in key.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            break
    if node is None and lang != "en":
        return t(key, "en", default, **kw)
    template = node if isinstance(node, str) else (default if default is not None else key)
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template


def chf(x: float | None, lang: str = "en") -> str:
    if x is None:
        return "–"
    return f"CHF {round(x):,}".replace(",", "'")


def month(d: date | None, lang: str = "en") -> str:
    if d is None:
        return "–"
    return str(d.year)          # the client sees years only (goal dates are June 1)


def pct(x: float) -> str:
    return f"{x:.0%}"
