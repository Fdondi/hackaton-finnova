"""Turns a list of LeverImpacts into dense (months x paths) arrays the simulation loop can add up."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from ..model import LeverImpact, months_between
from .market import Market
from .random import stream


@dataclass
class Compiled:
    T: int
    N: int
    flow: np.ndarray                  # today's CHF added to cash each month (indexed with prices)
    flow_nominal: np.ndarray          # nominal CHF
    salary_factor: np.ndarray         # multiplies salary (and gross income / pension credits if affects_gross)
    gross_factor: np.ndarray
    to_bucket_monthly: dict[str, np.ndarray] = field(default_factory=dict)   # today's CHF moved from cash each month
    one_off: dict[str, np.ndarray] = field(default_factory=dict)             # today's CHF added to bucket (+/-)
    transfers: list[tuple[int, str, str, np.ndarray]] = field(default_factory=list)
    withdrawals: list[tuple[int, np.ndarray, list[str], dict[str, float], bool]] = field(default_factory=list)
    settings: dict = field(default_factory=dict)


def _span(start: date, s: date, e: date | None, T: int) -> tuple[int, int]:
    t0 = max(0, months_between(start, s))
    t1 = T if e is None else min(T, months_between(start, e) + 1)
    return t0, max(t0, t1)


def compile_impacts(impacts: list[LeverImpact], start: date, T: int, N: int, seed: int, market: Market) -> Compiled:
    c = Compiled(T=T, N=N, flow=np.zeros((T, N)), flow_nominal=np.zeros((T, N)),
                 salary_factor=np.ones((T, N)), gross_factor=np.ones((T, N)))

    def bucket(d: dict, name: str) -> np.ndarray:
        if name not in d:
            d[name] = np.zeros((T, N))
        return d[name]

    for lever in impacts:
        c.settings.update(lever.settings)
        k = 0
        for r in lever.recurring:
            k += 1
            t0, t1 = _span(start, r.start, r.end, T)
            if t1 <= t0:
                continue
            n = t1 - t0
            rng = stream(seed, lever.lever_id, k)
            if r.resample == "once":
                vals = np.broadcast_to(r.monthly.sample(rng, N), (n, N)).copy()
            elif r.resample == "yearly":
                years = int(np.ceil(n / 12))
                vals = np.repeat(r.monthly.sample(rng, (years, N)), 12, axis=0)[:n]
            else:
                vals = r.monthly.sample(rng, (n, N))
            if r.behavioural:
                age = np.arange(n)[:, None]
                vals = vals * (market.haircut_floor + (1 - market.haircut_floor) * np.exp(-age / market.haircut_tau))
            (c.flow if r.indexed else c.flow_nominal)[t0:t1] += vals
        for s in lever.shocks:
            k += 1
            t0, t1 = _span(start, s.start, s.end, T)
            if t1 <= t0:
                continue
            rng = stream(seed, lever.lever_id, k)
            hit = rng.uniform(size=(t1 - t0, N)) < s.annual_prob / 12
            c.flow[t0:t1] -= hit * s.severity.sample(rng, (t1 - t0, N))
        for inc in lever.income_changes:
            k += 1
            t0, t1 = _span(start, inc.start, inc.end, T)
            if t1 <= t0:
                continue
            if inc.salary_factor is not None:
                c.salary_factor[t0:t1] *= inc.salary_factor
                if inc.affects_gross:
                    c.gross_factor[t0:t1] *= inc.salary_factor
            if inc.monthly_net is not None:
                c.flow[t0:t1] += inc.monthly_net.sample(stream(seed, lever.lever_id, k), N)
        for a in lever.allocation_changes:
            k += 1
            t0, t1 = _span(start, a.start, a.end, T)
            if t1 <= t0:
                continue
            rng = stream(seed, lever.lever_id, k)
            if a.mode == "monthly":
                vals = a.amount.sample(rng, N)
                if a.from_bucket == "cash":
                    bucket(c.to_bucket_monthly, a.to_bucket)[t0:t1] += vals
                else:
                    c.transfers.extend((t, a.from_bucket, a.to_bucket, vals) for t in range(t0, t1))
            else:
                c.transfers.append((t0, a.from_bucket, a.to_bucket, a.amount.sample(rng, N)))
        for o in lever.one_offs:
            k += 1
            t = months_between(start, o.at)
            if 0 <= t < T:
                vals = o.amount.sample(stream(seed, lever.lever_id, k), N)
                if o.indexed:
                    bucket(c.one_off, o.bucket)[t] += vals
                elif o.bucket == "cash":
                    c.flow_nominal[t] += vals
                else:
                    bucket(c.one_off, o.bucket)[t] += vals
        for w in lever.withdrawals:
            k += 1
            t = months_between(start, w.at)
            if 0 <= t < T:
                c.withdrawals.append((t, w.amount.sample(stream(seed, lever.lever_id, k), N), list(w.order), dict(w.caps), w.house_indexed))
    return c
