"""Small tagged union of distributions that levers use for uncertain amounts."""
from __future__ import annotations

from typing import Annotated, Literal, Union

import numpy as np
from pydantic import BaseModel, Field


class _DistBase(BaseModel):
    def sample(self, rng: np.random.Generator, size) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError

    def mean(self) -> float:  # pragma: no cover
        raise NotImplementedError

    def band(self) -> tuple[float, float]:
        """Rough P10/P90, for display."""
        s = self.sample(np.random.default_rng(0), 4000)
        return float(np.percentile(s, 10)), float(np.percentile(s, 90))

    def scaled(self, k: float) -> "Dist":  # pragma: no cover
        raise NotImplementedError


class Fixed(_DistBase):
    kind: Literal["fixed"] = "fixed"
    value: float

    def sample(self, rng, size):
        return np.full(size, self.value, dtype=float)

    def mean(self):
        return self.value

    def band(self):
        return self.value, self.value

    def scaled(self, k):
        return Fixed(value=self.value * k)


class Normal(_DistBase):
    kind: Literal["normal"] = "normal"
    mu: float
    sd: float

    def sample(self, rng, size):
        return self.mu + self.sd * rng.standard_normal(size)

    def mean(self):
        return self.mu

    def scaled(self, k):
        return Normal(mu=self.mu * k, sd=abs(self.sd * k))


class LogNormal(_DistBase):
    """Positive amounts. sign=-1 for costs expressed as negative money."""
    kind: Literal["lognormal"] = "lognormal"
    median: float
    sigma: float
    sign: Literal[1, -1] = 1

    def sample(self, rng, size):
        return self.sign * self.median * np.exp(self.sigma * rng.standard_normal(size))

    def mean(self):
        return self.sign * self.median * float(np.exp(self.sigma**2 / 2))

    def scaled(self, k):
        return LogNormal(median=self.median * abs(k), sigma=self.sigma, sign=self.sign * (1 if k >= 0 else -1))


class Uniform(_DistBase):
    kind: Literal["uniform"] = "uniform"
    low: float
    high: float

    def sample(self, rng, size):
        return rng.uniform(self.low, self.high, size)

    def mean(self):
        return (self.low + self.high) / 2

    def band(self):
        w = self.high - self.low
        return self.low + 0.1 * w, self.high - 0.1 * w

    def scaled(self, k):
        a, b = sorted((self.low * k, self.high * k))
        return Uniform(low=a, high=b)


class Triangular(_DistBase):
    """The natural shape for 'somewhere between low and high, most likely mode' estimates."""
    kind: Literal["triangular"] = "triangular"
    low: float
    mode: float
    high: float

    def sample(self, rng, size):
        if self.high <= self.low:
            return np.full(size, self.mode, dtype=float)
        return rng.triangular(self.low, min(max(self.mode, self.low), self.high), self.high, size)

    def mean(self):
        return (self.low + self.mode + self.high) / 3

    def scaled(self, k):
        vals = sorted((self.low * k, self.high * k))
        return Triangular(low=vals[0], mode=self.mode * k, high=vals[1])


class Empirical(_DistBase):
    kind: Literal["empirical"] = "empirical"
    samples: list[float]

    def sample(self, rng, size):
        return rng.choice(np.asarray(self.samples, dtype=float), size=size, replace=True)

    def mean(self):
        return float(np.mean(self.samples))

    def band(self):
        return float(np.percentile(self.samples, 10)), float(np.percentile(self.samples, 90))

    def scaled(self, k):
        return Empirical(samples=[s * k for s in self.samples])


Dist = Annotated[Union[Fixed, Normal, LogNormal, Uniform, Triangular, Empirical], Field(discriminator="kind")]


def fixed(v: float) -> Fixed:
    return Fixed(value=float(v))


def normal(mean: float, sd: float) -> Normal:
    return Normal(mu=float(mean), sd=float(sd))


def lognormal(median: float, sigma: float, sign: int = 1) -> LogNormal:
    return LogNormal(median=float(median), sigma=float(sigma), sign=sign)


def uniform(low: float, high: float) -> Uniform:
    return Uniform(low=float(low), high=float(high))


def triangular(low: float, mode: float, high: float) -> Triangular:
    lo, hi = min(low, high), max(low, high)
    return Triangular(low=float(lo), mode=float(min(max(mode, lo), hi)), high=float(hi))


def empirical(samples) -> Empirical:
    return Empirical(samples=[float(x) for x in samples])
