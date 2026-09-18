"""People like you: statistics measured on the bank's population data (written by scripts/prep_testdata.py).

Registered as the "population" service. When the data directory has no population/ folder (e.g. the synthetic
personas) the service is empty, and every consumer keeps its config defaults: numbers only get the `population`
source label when they really come from the data.

    risk_for(ds, profile)  big unexpected bills, salary gaps and spending noise for this client's segment, blended
                           with the client's own 12 months (credibility weighting)
    life_event(name)       what changed for people after a birth, wedding, separation, job change, ...
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .categorise import load_taxonomy
from .config import Config, resolve_path
from .model import Dataset
from .profile import Profile
from .services import service

# categories where a large payment is a planned fixed cost, not a surprise
NOT_A_SURPRISE = {"housing", "taxes", "health_premium", "insurance_other", "car_financing", "childcare",
                  "family_support", "cash", "card_lump", "transfers_p2p"}
PRIOR_YEARS = 2.0          # the segment counts like two years of the client's own history
MIN_SEGMENT = 30           # smaller segments fall back to everyone


def age_band(age: float) -> str:
    return "18-29" if age < 30 else "30-44" if age < 45 else "45-64" if age < 65 else "65+"


def emp_group(e: str | None) -> str:
    return e if e in ("employed", "self_employed", "retired", "student") else "other"


@dataclass
class RiskProfile:
    segment: str
    segment_label: str
    n_people: int
    bill_threshold: float
    bill_rate: float                 # expected bills >= threshold per year (blended)
    bill_mu: float                   # lognormal size, today's CHF
    bill_sigma: float
    bill_p50: float | None
    bill_p90: float | None
    share_with_bill: float
    personal_bills: int              # seen in the client's own window
    personal_bill_monthly: float     # their average per month (already inside variable spending)
    segment_rate: float
    salary_gap_prob: float | None    # per year, None = not enough earners in the segment
    salary_gap_months: float | None
    expense_noise_sd: float | None
    top_causes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def bill_mean(self) -> float:
        return math.exp(self.bill_mu + 0.5 * self.bill_sigma ** 2)

    def year_total(self, q: float = 0.9, n: int = 20_000) -> float:
        """The q-quantile of one year's bills (compound Poisson): "in a bad year (1 in 10) they add up to ..."."""
        rng = np.random.default_rng(20260918)
        counts = rng.poisson(self.bill_rate, n)
        total = np.zeros(n)
        for k in range(int(counts.max())):
            total += np.where(counts > k, rng.lognormal(self.bill_mu, self.bill_sigma, n), 0.0)
        return float(np.quantile(total, q))


class PopulationStats:
    def __init__(self, cfg: Config):
        self.dir = resolve_path(cfg.get_path("app.data.dir", "data")) / "population"
        self.risk = self._json("risk.json")
        self.events = self._json("life_events.json")

    def _json(self, name: str) -> dict:
        p: Path = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    @property
    def available(self) -> bool:
        return bool(self.risk)

    def segment(self, age: float, employment: str | None) -> tuple[str, dict]:
        segs = self.risk.get("segments", {})
        key = f"{age_band(age)}|{emp_group(employment)}"
        s = segs.get(key)
        if s and s.get("n_people", 0) >= MIN_SEGMENT:
            return key, s
        return "all", segs.get("all", {})

    def risk_for(self, ds: Dataset, profile: Profile) -> RiskProfile | None:
        if not self.available:
            return None
        age = float(profile.age or 40)
        employment = ds.client.extra.get("employment_type")
        key, s = self.segment(age, employment)
        threshold = float(self.risk.get("big_bill_threshold", 1000))
        tax = load_taxonomy()
        recurring = {bid for r in profile.recurring for bid in r.booking_ids}
        bills = [b for b in ds.bookings
                 if b.amount <= -threshold and profile.window_start <= b.booking_date <= profile.as_of
                 and b.category not in NOT_A_SURPRISE and tax.kind(b.category or "") == "spending" and b.id not in recurring]
        years = max(profile.covered_months, 1) / 12
        seg_rate = float(s.get("bill_rate", 0.0))
        rate = (PRIOR_YEARS * seg_rate + len(bills)) / (PRIOR_YEARS + years)          # Poisson-Gamma posterior mean
        # salary gaps only calibrate job-loss risk for employees, and only if the data shows any: the self-employed
        # "gaps" are an irregular payment rhythm, and zero gaps in 12 months doesn't prove zero risk
        gap_ok = (emp_group(employment) == "employed" and s.get("n_earners", 0) >= MIN_SEGMENT
                  and (s.get("interrupt_prob") or 0) > 0)
        if key == "all":
            label = "everyone in the data"
        else:
            band, emp = key.split("|")
            label = f"{emp.replace('_', '-')} people aged {band}"
        return RiskProfile(
            segment=key, segment_label=label,
            n_people=int(s.get("n_people", 0)), bill_threshold=threshold, bill_rate=round(rate, 3),
            bill_mu=float(s.get("bill_mu", 7.9)), bill_sigma=float(s.get("bill_sigma", 0.8)),
            bill_p50=s.get("bill_p50"), bill_p90=s.get("bill_p90"), share_with_bill=float(s.get("share_with_bill", 0.0)),
            personal_bills=len(bills), personal_bill_monthly=round(-sum(b.amount for b in bills) / max(profile.covered_months, 1), 2),
            segment_rate=seg_rate,
            salary_gap_prob=float(s["interrupt_prob"]) if gap_ok else None,
            salary_gap_months=float(s["interrupt_median_months"]) if gap_ok and s.get("interrupt_median_months") else None,
            expense_noise_sd=s.get("spend_noise_cv"),
            top_causes=self.risk.get("top_causes", [])[:5],
        )

    def life_event(self, name: str) -> dict | None:
        e = self.events.get("events", {}).get(name)
        return e if e and e.get("status") == "ok" else None


@service("population")
def _population(cfg: Config) -> PopulationStats:
    return PopulationStats(cfg)
