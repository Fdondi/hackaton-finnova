"""InsurerQuoteService: the seam where an insurer's agent or a comparison service plugs in.

The bank asks "what would basic insurance cost this client with deductible d?" and consumes the answer
as a projection input. Supplementary insurance (VVG, with underwriting) stays insurer-side.
"""
from __future__ import annotations

from typing import Protocol

from ..config import Config
from ..services import service


class InsurerQuoteService(Protocol):
    def quote(self, *, age: float, canton: str | None, deductible: int, model: str = "standard",
              accident_cover: bool = True) -> float:
        """Monthly premium in CHF."""
        ...


class MockInsurerQuotes:
    source = "mock premium table (config/insurer_premiums.yaml)"

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.t = cfg["insurer_premiums"]
        self.kvg = cfg["kvg"]

    def quote(self, *, age, canton, deductible, model="standard", accident_cover=True) -> float:
        base = self.cfg.by_canton("insurer_premiums.base_premium_300", canton, 440)
        age_f = next(r["factor"] for r in self.t["age_factor"] if age <= r["max_age"])
        base *= age_f * self.t["model_factor"].get(model or "standard", 1.0)
        if not accident_cover:
            base *= self.t["without_accident_cover_factor"]
        max_discount = self.kvg["max_discount_share_of_extra_risk"] * max(0, deductible - 300)
        return max(base - self.t["deductible_discount_share_of_max"] * max_discount / 12, base * 0.3)


@service("insurer_quotes", "mock")
def _mock(cfg: Config) -> InsurerQuoteService:
    return MockInsurerQuotes(cfg)
