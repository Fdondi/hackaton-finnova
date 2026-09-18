"""Common random numbers: every scenario for a client sees the same simulated futures.

That makes toggles stable (no jitter), keeps lever comparisons fair, and makes bisection monotone.
Lever-specific randomness gets its own stream keyed by lever id, so adding a lever never changes
the draws of the baseline or of other levers.
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np


@dataclass(frozen=True)
class RandomBank:
    z_market: np.ndarray    # (T, N)
    z_infl: np.ndarray
    z_house: np.ndarray
    z_expense: np.ndarray
    u_job: np.ndarray
    z_job_duration: np.ndarray
    u_bill: np.ndarray      # drawn last: adding them left every earlier draw (and every golden number) unchanged
    z_bill: np.ndarray


@lru_cache(maxsize=16)
def random_bank(seed: int, months: int, paths: int) -> RandomBank:
    rng = np.random.default_rng(seed)
    shape = (months, paths)
    return RandomBank(
        z_market=rng.standard_normal(shape), z_infl=rng.standard_normal(shape), z_house=rng.standard_normal(shape),
        z_expense=rng.standard_normal(shape), u_job=rng.uniform(size=shape), z_job_duration=rng.standard_normal(shape),
        u_bill=rng.uniform(size=shape), z_bill=rng.standard_normal(shape),
    )


def bank_for(seed: int, months: int, paths: int) -> RandomBank:
    """Slices of a bank generated for a round horizon, so short and long runs share the same first months."""
    rounded = max(120, int(np.ceil(months / 120) * 120))
    b = random_bank(seed, rounded, paths)
    return RandomBank(*(getattr(b, f)[:months] for f in RandomBank.__dataclass_fields__))


def stream(seed: int, key: str, idx: int = 0) -> np.random.Generator:
    return np.random.default_rng([seed, zlib.crc32(key.encode()), idx])
