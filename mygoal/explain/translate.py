"""Translate the engine's English labels and sentences for display (exact phrases, then patterns, then unit words).

The engine and its plugins write English; `mygoal/explain/i18n/<lang>.yaml` holds, per language:
  labels:          exact phrases            "Fixed costs per month": "Fixkosten pro Monat"
  label_patterns:  [regex, replacement]     templated sentences with numbers ("About (.+)/month. ...")
  unit_words:      units and suffixes       "CHF/month": "CHF/Monat"
Unknown text passes through unchanged, so a missing entry shows English instead of breaking anything.
"""
from __future__ import annotations

import re
from functools import lru_cache

from .texts import strings


@lru_cache(maxsize=8)
def _table(lang: str):
    s = strings(lang)
    pats = [(re.compile(p), r) for p, r in s.get("label_patterns", [])]
    return s.get("labels", {}), pats, s.get("unit_words", {})


def tr(text: str | None, lang: str) -> str | None:
    if not text or lang == "en":
        return text
    exact, pats, _ = _table(lang)
    if text in exact:
        return exact[text]
    for rx, rep in pats:
        if rx.fullmatch(text):
            return rx.sub(rep, text)
    return text


def tr_unit(unit: str | None, lang: str) -> str | None:
    if not unit or lang == "en":
        return unit
    return _table(lang)[2].get(unit, unit)
