"""Every number the client sees carries a source tag and, where sensible, a range they can edit.

Builders don't handle user edits themselves: they call `book.get(...)` with their default,
and the book returns the user's override when there is one (re-tagged as source="user").
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Source = Literal["transactions", "client_data", "user", "market_default", "llm_estimate", "population"]


class Assumption(BaseModel):
    key: str
    label: str
    value: float
    low: float | None = None
    high: float | None = None
    unit: str = "CHF"
    source: Source
    editable: bool = True
    needs_confirmation: bool = False   # a guess about the person: the advisor view lists these
    note: str | None = None
    step: float | None = None


class AssumptionBook:
    def __init__(self, overrides: dict[str, float] | None = None, prefix: str = ""):
        self.overrides = dict(overrides or {})
        self.prefix = prefix
        self.items: dict[str, Assumption] = {}

    def get(
        self,
        key: str,
        value: float,
        *,
        label: str,
        source: Source,
        unit: str = "CHF",
        low: float | None = None,
        high: float | None = None,
        editable: bool = True,
        needs_confirmation: bool = False,
        note: str | None = None,
        step: float | None = None,
    ) -> float:
        value = float(value)
        key = self.prefix + key
        if key in self.overrides and editable:
            value = float(self.overrides[key])
            source = "user"
            needs_confirmation = False
        if low is not None and high is not None:
            low, high = min(low, value), max(high, value)
        self.items[key] = Assumption(
            key=key, label=label, value=value, low=low, high=high, unit=unit, source=source,
            editable=editable, needs_confirmation=needs_confirmation, note=note, step=step,
        )
        return value

    def add(self, a: Assumption) -> float:
        return self.get(
            a.key[len(self.prefix):] if self.prefix and a.key.startswith(self.prefix) else a.key, a.value, label=a.label, source=a.source, unit=a.unit, low=a.low, high=a.high,
            editable=a.editable, needs_confirmation=a.needs_confirmation, note=a.note, step=a.step,
        )

    def list(self) -> list[Assumption]:
        return list(self.items.values())
