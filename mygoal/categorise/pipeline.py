"""Booking categoriser: a list of stages, first hit wins.

    internal transfer -> bank category -> rules.yaml -> merchants.yaml -> MCC -> LLM (optional) -> fallback

Each stage is a small function, so reordering or adding one (e.g. a bank-specific stage) is a one-line change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable

import yaml

from ..model import Booking, Dataset

HERE = Path(__file__).parent

_PREFIXES = re.compile(
    r"^(twint \*|einkauf |zahlung |lastschrift |gutschrift |lsv |dauerauftrag |e-banking |debit |kauf |"
    r"rechnung |auftrag |belastung )+"
)
_NOISE = re.compile(r"karte x+\s*\d*|\b\d{1,2}[./]\d{1,2}([./]\d{2,4})?\b|\b[a-z]*\d[\w-]*\b|[^\w\s&.äöüéèà]")
_LEGAL = re.compile(r"(?<![\w.])(ag|gmbh|sa|s\.a\.|b\.v\.|bv|ab|ltd|inc|kg|co)(?![\w])\.?")


def normalise_merchant(b: Booking) -> str:
    src = (b.counterparty or b.text or "").lower()
    src = src.split(" | ")[0]
    s = _PREFIXES.sub("", src.strip())
    s = _NOISE.sub(" ", s)
    s = _LEGAL.sub(" ", s)
    tokens = [t for t in s.split() if len(t) > 1][:4]
    return " ".join(tokens) or "unknown"


@dataclass
class Taxonomy:
    categories: dict[str, dict]

    def kind(self, cat: str) -> str:
        return self.categories.get(cat, {}).get("kind", "spending")

    def is_(self, cat: str, attr: str) -> bool:
        return bool(self.categories.get(cat, {}).get(attr))

    def label(self, cat: str, lang: str = "en") -> str:
        lbl = self.categories.get(cat, {}).get("label", {})
        return lbl.get(lang) or lbl.get("en") or cat

    def with_attr(self, attr: str) -> list[str]:
        return [c for c, v in self.categories.items() if v.get(attr)]

    def of_kind(self, kind: str) -> list[str]:
        return [c for c, v in self.categories.items() if v.get("kind") == kind]


@lru_cache(maxsize=1)
def load_taxonomy() -> Taxonomy:
    return Taxonomy(yaml.safe_load((HERE / "taxonomy.yaml").read_text(encoding="utf-8"))["categories"])


def _load(name: str) -> dict:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


Stage = Callable[[Booking, "Categoriser"], tuple[str, str, list[str]] | None]


class Categoriser:
    def __init__(self, llm_stage: Callable[[list[Booking]], None] | None = None):
        self.taxonomy = load_taxonomy()
        self.rules = [
            ({k: re.compile(v, re.I) for k, v in r["when"].items() if k != "sign"}, r["when"].get("sign"), r)
            for r in _load("rules.yaml")["rules"]
        ]
        merchants = _load("merchants.yaml")["merchants"]
        self.merchants = sorted(merchants.items(), key=lambda kv: -len(kv[0]))
        self.mcc_exact, self.mcc_ranges = {}, []
        for k, v in _load("mcc.yaml")["mcc"].items():
            if "-" in str(k):
                lo, hi = map(int, str(k).split("-"))
                self.mcc_ranges.append((lo, hi, v))
            else:
                self.mcc_exact[str(k)] = v
        self.bank_map: dict[str, str] = (_load("bank_categories.yaml") or {}).get("map", {}) \
            if (HERE / "bank_categories.yaml").exists() else {}
        self.own_ibans: set[str] = set()
        self.llm_stage = llm_stage
        self.stages: list[tuple[str, Stage]] = [
            ("internal", Categoriser.stage_internal),
            ("bank", Categoriser.stage_bank),
            ("rule", Categoriser.stage_rules),
            ("merchant", Categoriser.stage_merchant),
            ("mcc", Categoriser.stage_mcc),
        ]

    # ---- stages: return (category, source, tags) or None ----
    def stage_internal(self, b: Booking):
        if b.counterparty_iban and b.counterparty_iban in self.own_ibans:
            return "internal_transfer", "internal", []
        if (b.bank_tx_code or "").endswith("-BOOK") and re.search(r"übertrag|umbuchung|transfer", b.text, re.I):
            return "internal_transfer", "internal", []
        return None

    def stage_bank(self, b: Booking):
        if b.bank_category:
            cat = self.bank_map.get(b.bank_category, b.bank_category)
            if cat in self.taxonomy.categories:
                return cat, "bank", []
        return None

    def stage_rules(self, b: Booking):
        fields = {
            "text": f"{b.text} | {b.counterparty or ''}",
            "counterparty": b.counterparty or "",
            "merchant": b.merchant or "",
            "bank_tx_code": b.bank_tx_code or "",
            "mcc": b.mcc or "",
        }
        for patterns, sign, rule in self.rules:
            if sign == "+" and b.amount <= 0 or sign == "-" and b.amount >= 0:
                continue
            if all(p.search(fields.get(k, "")) for k, p in patterns.items()):
                return rule["category"], "rule", list(rule.get("tags", []))
        return None

    def stage_merchant(self, b: Booking):
        hay = f"{b.merchant} {b.text} {b.counterparty or ''}".lower()
        for key, info in self.merchants:
            if key in hay:
                return info["category"], "merchant", list(info.get("tags", []))
        return None

    def stage_mcc(self, b: Booking):
        if not b.mcc:
            return None
        if b.mcc in self.mcc_exact:
            return self.mcc_exact[b.mcc], "mcc", []
        try:
            code = int(b.mcc)
        except ValueError:
            return None
        for lo, hi, cat in self.mcc_ranges:
            if lo <= code <= hi:
                return cat, "mcc", []
        return None

    # ---- driver ----
    def categorise(self, ds: Dataset) -> Dataset:
        self.own_ibans = {a.id for a in ds.accounts} | {a.iban for a in ds.accounts if a.iban}
        unknown: list[Booking] = []
        for b in ds.bookings:
            if b.category_source == "user":
                continue
            b.merchant = normalise_merchant(b)
            for _, stage in self.stages:
                hit = stage(self, b)
                if hit:
                    b.category, b.category_source, b.tags = hit[0], hit[1], sorted(set(b.tags) | set(hit[2]))
                    break
            else:
                unknown.append(b)
        if unknown and self.llm_stage:
            self.llm_stage(unknown)
        for b in unknown:
            if b.category is None:
                bank_guess = b.extra.get("fallback_category") if b.amount < 0 else None   # adapter's coarse category
                if bank_guess in self.taxonomy.categories:
                    b.category, b.category_source = bank_guess, "bank"
                    continue
                b.category = "income_other" if b.amount > 0 else "unexplained"
                b.category_source = "fallback"
        return ds
