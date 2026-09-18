"""Turns simulations into answers: how likely, by when, how big is the gap, until when can I wait,
which levers matter most, and the smallest plan that gets me there. Goal-agnostic.
"""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel

from ..config import Config
from ..goals import GOALS, GoalEval, parse_params, target_date
from ..model import GoalChange, GoalSpec, LeverImpact, RecurringDelta, add_months, fixed, months_between
from .baseline import Baseline
from .market import Market
from .simulate import simulate


class DateBand(BaseModel):
    p10: date | None
    p50: date | None
    p90: date | None
    never_share: float
    horizon_end: date


class WorstCaseSegment(BaseModel):
    """What a path tracking the bottom of the fan chart looks like, over one stretch of time.

    The p10 line isn't one simulated path (a different path can be worst each month), so we pick the single
    path that best explains the band over each stretch and describe what happened to it, rather than pretend
    there's one continuous "worst case" story for the whole horizon.
    """
    start: date
    end: date
    job_loss_months: int = 0
    job_loss_start: date | None = None
    market_shortfall: float = 0.0   # 0..1: how far this path's investment growth trailed a typical path
    text: str = ""                  # filled in by the service layer, which knows the language


class FanChart(BaseModel):
    dates: list[date]
    p_min: list[float]
    p10: list[float]
    p25: list[float]
    p50: list[float]
    p75: list[float]
    p90: list[float]
    p_max: list[float]
    need: list[float]
    have_label: str
    need_label: str
    worst_case: list[WorstCaseSegment] = []


class GoalOutcome(BaseModel):
    goal_id: str
    start: date
    target_date: date
    p_success: float
    futures_of_10: int
    achieved: DateBand
    months_late: int | None
    have_at_target: float
    need_at_target: float
    shortfall_at_target: float
    binding: str | None
    constraint_pass: dict[str, float]
    p_buffer_breach: float
    fan: FanChart | None = None


class Deadline(BaseModel):
    status: Literal["on_track", "ok", "not_enough"]
    start_by: date | None = None
    months_of_slack: int | None = None
    p_with_plan: float | None = None


class LeverScore(BaseModel):
    lever_id: str
    months_gained: int | None
    delta_p: float
    p_success: float
    achieved_p50: date | None
    monthly_equivalent: float


def monthly_equivalent(lever: LeverImpact, start: date, months: int, salary_monthly: float = 0.0) -> float:
    """Ongoing CHF/month this lever changes (display only; the engine uses the full distributions).

    One-off purchases and sales are not converted into a monthly figure: they hit cash at their date, like a goal.
    """
    months = max(months, 1)
    end = add_months(start, months)
    monthly = 0.0
    for r in lever.recurring:
        a, b = max(r.start, start), min(r.end or end, end)
        if max(0, months_between(a, b) + (1 if r.end else 0)) <= 0:
            continue
        monthly += r.monthly.mean() * (0.75 if r.behavioural else 1.0)
    for i in lever.income_changes:
        a, b = max(i.start, start), min(i.end or end, end)
        if max(0, months_between(a, b) + (1 if i.end else 0)) <= 0:
            continue
        if i.monthly_net is not None:
            monthly += i.monthly_net.mean()
        if i.salary_factor is not None:
            monthly += (i.salary_factor - 1) * salary_monthly
    for s in lever.shocks:
        a, b = max(s.start, start), min(s.end or end, end)
        if max(0, months_between(a, b)) <= 0:
            continue
        monthly -= s.annual_prob / 12 * s.severity.mean()
    for inv in lever.investments:
        monthly += _investment_monthly(inv, start, end)
    return monthly


def _investment_lines(inv, start: date, end: date, months: int) -> list[tuple[str, float]]:
    """Expected extra CHF/month from an investment pot: return on the average balance, not the capital itself."""
    rate = _investment_monthly(inv, start, end)
    return [("return", rate)] if rate else []


def _investment_monthly(inv, start: date, end: date) -> float:
    n = max(0, months_between(max(inv.start, start), end))
    once = inv.once.mean() if inv.once is not None else 0.0
    contrib = inv.monthly.mean() if inv.monthly is not None else 0.0
    avg_balance = once + contrib * n / 2
    return avg_balance * inv.expected_return / 12 if n else 0.0


def breakdown(lever: LeverImpact, start: date, months: int, salary_monthly: float = 0.0) -> dict:
    """How the monthly figure on a card comes about: the ongoing income or cost (after tax, habits, expected return),
    plus any one-off purchase/sale listed separately — that outflow is instantaneous, like a goal, not a monthly amount."""
    months = max(months, 1)
    end = add_months(start, months)
    lines = []
    for r in lever.recurring:
        a, b = max(r.start, start), min(r.end or end, end)
        n = max(0, months_between(a, b) + (1 if r.end else 0))
        share = 0.75 if r.behavioural else 1.0
        if n:
            monthly = round(r.monthly.mean() * share, 2)
            explain = (f"{share:.0%} of this change counted long-term (habits fade)" if share < 1
                       else f"CHF {r.monthly.mean():,.0f}/month".replace(",", "'"))
            lines.append({"label": r.label or lever.title, "kind": "monthly", "amount": round(r.monthly.mean(), 2), "months": n,
                          "share": share, "monthly": monthly, "explain": explain})
    for o in lever.one_offs:
        if start <= o.at < end and o.bucket == "cash":
            amt = o.amount.mean()
            verb = "received" if amt > 0 else "paid"
            lines.append({"label": o.label or lever.title, "kind": "once", "amount": round(amt, 2), "months": 0,
                          "monthly": 0.0,
                          "explain": f"CHF {amt:,.0f} {verb} once at that date, like a goal — not part of the monthly figure".replace(",", "'")})
    for i in lever.income_changes:
        a, b = max(i.start, start), min(i.end or end, end)
        n = max(0, months_between(a, b) + (1 if i.end else 0))
        if n and i.monthly_net is not None:
            lines.append({"label": i.label or lever.title, "kind": "monthly", "amount": round(i.monthly_net.mean(), 2), "months": n,
                          "share": 1.0, "monthly": round(i.monthly_net.mean(), 2),
                          "explain": f"CHF {i.monthly_net.mean():,.0f}/month".replace(",", "'")})
        if n and i.salary_factor is not None:
            amt = (i.salary_factor - 1) * salary_monthly
            lines.append({"label": i.label or lever.title, "kind": "monthly", "amount": round(amt, 2), "months": n, "share": 1.0,
                          "monthly": round(amt, 2),
                          "explain": f"Salary change of {amt:,.0f}/month".replace(",", "'")})
    for inv in lever.investments:
        for _, v in _investment_lines(inv, start, end, months):
            lines.append({"label": inv.label or lever.title, "kind": "return", "rate": inv.expected_return,
                          "amount": round(v, 2), "months": months, "monthly": round(v, 2),
                          "explain": f"Expected return only (the capital itself stays yours); {inv.expected_return:.0%}/year"})
    monthly_lines = [x for x in lines if x["kind"] != "once"]
    once = round(sum(x["amount"] for x in lines if x["kind"] == "once"), 2)
    return {"lines": lines, "months": months, "until": end, "notes": list(lever.details.get("notes", [])),
            "total": round(sum(x["monthly"] for x in monthly_lines), 2), "once": once}


def apply_goal_changes(spec: GoalSpec, impacts: list[LeverImpact]) -> GoalSpec:
    changes = [g for lever in impacts for g in lever.goal_changes if g.goal_id in (None, spec.id)]
    if not changes:
        return spec
    spec = spec.model_copy(deep=True)
    for ch in changes:
        if ch.field == "target_date":
            if spec.target_date:
                spec.target_date = add_months(spec.target_date, int(ch.value)) if ch.op in ("add", "add_months") else spec.target_date
            continue
        cur = spec.params.get(ch.field)
        if ch.op == "add" and cur is None and ch.field == "retirement_age":
            cur = 65
        if ch.op == "set":
            spec.params[ch.field] = bool(ch.value) if isinstance(cur, bool) else ch.value
        elif ch.op == "mul" and cur is not None:
            spec.params[ch.field] = cur * ch.value
        elif ch.op == "add" and cur is not None:
            spec.params[ch.field] = cur + ch.value
    return spec


def _key(impacts: list[LeverImpact], T: int) -> str:
    h = hashlib.sha1(str(T).encode())
    for i in impacts:
        h.update(i.model_dump_json(exclude={"assumptions", "side_effects", "description", "title"}).encode())
    return h.hexdigest()


class Planner:
    def __init__(self, base: Baseline, market: Market, goal: GoalSpec, cfg: Config, n_paths: int | None = None,
                 seed: int | None = None):
        self.base, self.market, self.goal, self.cfg = base, market, goal, cfg
        sim = cfg["app"]["simulation"]
        self.N = n_paths or sim["n_paths"]
        self.seed = seed if seed is not None else sim["seed"]
        self.threshold = sim["success_threshold"]
        self.plugin = GOALS.get(goal.type)
        self._cache: dict[str, GoalOutcome] = {}
        self._p_cache: dict[str, float] = {}

    # ---- horizon ----
    def _target(self, spec: GoalSpec) -> date:
        t = target_date(self.plugin, spec, self.base)
        return max(t, add_months(self.base.start, 1))

    def _horizon(self, spec: GoalSpec, params) -> int:
        sim = self.cfg["app"]["simulation"]
        tgt = self._target(spec)
        end = getattr(self.plugin, "horizon_end", lambda *a: None)(spec, params, self.base) \
            or add_months(tgt, 12 * sim["horizon_years_after_target"])
        T = months_between(self.base.start, end)
        return int(np.clip(T, months_between(self.base.start, tgt) + 1, 12 * sim["max_horizon_years"]))

    # ---- core ----
    def _evaluate(self, impacts: list[LeverImpact], T: int | None):
        spec = apply_goal_changes(self.goal, impacts)
        params = parse_params(self.plugin, spec)
        tgt = self._target(spec)
        T = T or self._horizon(spec, params)
        traj = simulate(self.base, impacts, self.market, T, self.N, self.seed)
        ev: GoalEval = self.plugin.evaluate(spec, params, traj, self.base, self.cfg)
        return spec, tgt, traj, ev

    def _at_target(self, impacts: list[LeverImpact]) -> tuple[float, float]:
        """(P(success by target), mean funding ratio at target) from a short simulation that stops at the target."""
        spec = apply_goal_changes(self.goal, impacts)
        tidx = months_between(self.base.start, self._target(spec))
        key = _key(impacts, -tidx)
        if key not in self._p_cache:
            _, _, _, ev = self._evaluate(impacts, T=tidx)
            p = float(ev.feasible[: tidx + 1].any(axis=0).mean())
            ratio = float(np.clip(ev.have[tidx] / np.maximum(ev.need[tidx], 1.0), 0, 1).mean())
            self._p_cache[key] = (p, ratio)
        return self._p_cache[key]

    def p_success(self, impacts: list[LeverImpact]) -> float:
        return self._at_target(impacts)[0]

    def progress(self, impacts: list[LeverImpact]) -> float:
        """Smooth objective for plan search: success probability, plus partial credit for getting closer."""
        p, ratio = self._at_target(impacts)
        return p + 0.3 * ratio

    def outcome(self, impacts: list[LeverImpact], fan: bool = False) -> GoalOutcome:
        key = _key(impacts, 0) + ("f" if fan else "")
        if key in self._cache:
            return self._cache[key]
        spec, tgt, traj, ev = self._evaluate(impacts, None)
        T, tidx = traj.T, months_between(self.base.start, tgt)
        feas = ev.feasible
        first = np.where(feas.any(axis=0), feas.argmax(axis=0), T + 1)
        p = float((first <= tidx).mean())
        q = np.percentile(first, [10, 50, 90], method="nearest")
        to_date = lambda i: traj.date_at(int(i)) if i <= T else None  # noqa: E731
        have_t, need_t = ev.have[tidx], ev.need[tidx]
        failing = ~feas[tidx]
        constraint_pass = {k: float(v[tidx].mean()) for k, v in ev.constraints.items()}
        binding = None
        if failing.any() and ev.constraints:
            binding = max(ev.constraints, key=lambda k: float((~ev.constraints[k][tidx] & failing).mean()))
        out = GoalOutcome(
            goal_id=self.goal.id, start=self.base.start, target_date=tgt, p_success=round(p, 3), futures_of_10=int(np.floor(p * 10 + 0.5)),
            achieved=DateBand(p10=to_date(q[0]), p50=to_date(q[1]), p90=to_date(q[2]),
                              never_share=float((first > T).mean()), horizon_end=traj.date_at(T)),
            months_late=int(q[1] - tidx) if q[1] <= T else None,
            have_at_target=float(np.median(have_t)), need_at_target=float(np.median(need_t)),
            shortfall_at_target=float(np.median(np.maximum(need_t - have_t, 0))),
            binding=binding, constraint_pass=constraint_pass, p_buffer_breach=float(traj.breach.mean()),
            fan=self._fan(traj, ev, tidx, q) if fan else None,
        )
        self._cache[key] = out
        return out

    def _fan(self, traj, ev: GoalEval, tidx: int, q) -> FanChart:
        last = int(min(traj.T, max(tidx, q[2] if q[2] <= traj.T else traj.T) + 12))
        idx = list(range(0, last + 1, 3 if last > 60 else 1))
        if tidx not in idx:
            idx = sorted(set(idx) | {tidx})
        h = ev.have[idx]
        pct = np.percentile(h, [10, 25, 50, 75, 90], axis=1).round(0)
        return FanChart(
            dates=[traj.date_at(i) for i in idx],
            p_min=h.min(axis=1).round(0).tolist(), p10=pct[0].tolist(), p25=pct[1].tolist(), p50=pct[2].tolist(),
            p75=pct[3].tolist(), p90=pct[4].tolist(), p_max=h.max(axis=1).round(0).tolist(),
            need=np.median(ev.need[idx], axis=1).round(0).tolist(),
            have_label=ev.have_label, need_label=ev.need_label,
            worst_case=self._worst_case(traj, h, np.array(idx), pct[0]),
        )

    def _worst_case(self, traj, h: np.ndarray, idx: np.ndarray, p10: np.ndarray, max_segments: int = 3) -> list["WorstCaseSegment"]:
        """Split the horizon into up to `max_segments` stretches; in each, find the single simulated path
        that stays closest to the p10 line, and describe what happened to that path there."""
        n = len(idx)
        if n < 2:
            return []
        bounds = sorted({0, *(n * k // max_segments for k in range(1, max_segments)), n})
        raw = []
        for lo, hi in zip(bounds, bounds[1:]):
            if hi <= lo:
                continue
            dist = np.abs(h[lo:hi] - p10[lo:hi, None]).sum(axis=0)
            raw.append((int(idx[lo]), int(idx[hi - 1]), int(np.argmin(dist))))

        merged: list[tuple[int, int, int]] = []
        for lo, hi, n_star in raw:
            if merged and merged[-1][2] == n_star:
                merged[-1] = (merged[-1][0], hi, n_star)
            else:
                merged.append((lo, hi, n_star))

        segments = []
        for lo, hi, n_star in merged:
            gross = traj.gross[lo:hi + 1, n_star]
            unemployed = gross <= 0.01 * max(float(traj.gross[0, n_star]), 1.0)
            job_months, job_start = 0, None
            if unemployed.any():
                edges = np.flatnonzero(np.diff(np.concatenate(([False], unemployed, [False])).astype(int)))
                runs = [(edges[i], edges[i + 1]) for i in range(0, len(edges), 2)]
                a, b = max(runs, key=lambda r: r[1] - r[0])
                job_months, job_start = b - a, traj.date_at(lo + a)

            mkt = traj.market[[lo, hi]]
            growth_all = mkt[1] / mkt[0]
            shortfall = float(max(0.0, 1.0 - growth_all[n_star] / max(np.median(growth_all), 1e-6)))

            segments.append(WorstCaseSegment(start=traj.date_at(lo), end=traj.date_at(hi), job_loss_months=job_months,
                                             job_loss_start=job_start, market_shortfall=round(shortfall, 3)))
        return segments

    # ---- questions ----
    def extra_saving(self, amount: float) -> LeverImpact:
        return LeverImpact(lever_id="__gap__", title="Extra saving",
                           recurring=[RecurringDelta(start=self.base.start, monthly=fixed(amount))])

    def gap_monthly(self, impacts: list[LeverImpact], max_monthly: float = 40000) -> float | None:
        """Extra CHF/month (today's money) needed from now to reach the success threshold by the target date."""
        if self.p_success(impacts) >= self.threshold:
            return 0.0
        lo, hi = 0.0, 250.0
        while self.p_success(impacts + [self.extra_saving(hi)]) < self.threshold:
            lo, hi = hi, hi * 2
            if hi > max_monthly:
                return None
        for _ in range(9):
            mid = (lo + hi) / 2
            if self.p_success(impacts + [self.extra_saving(mid)]) >= self.threshold:
                hi = mid
            else:
                lo = mid
        return float(np.ceil(hi / 10) * 10)

    def deadline(self, plan: list[LeverImpact], fixed_impacts: list[LeverImpact] | None = None) -> Deadline:
        """Latest start for `plan` that still reaches the threshold ("start by March 2027 and you still make 2031")."""
        fixed_impacts = fixed_impacts or []
        if self.p_success(fixed_impacts) >= self.threshold:
            return Deadline(status="on_track")
        p_plan = self.p_success(fixed_impacts + plan)
        if not plan or p_plan < self.threshold:
            return Deadline(status="not_enough", p_with_plan=round(p_plan, 3))
        spec = apply_goal_changes(self.goal, fixed_impacts + plan)
        lo, hi = 0, max(0, months_between(self.base.start, self._target(spec)))
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.p_success(fixed_impacts + [lv.shifted(mid) for lv in plan]) >= self.threshold:
                lo = mid
            else:
                hi = mid - 1
        return Deadline(status="ok", start_by=add_months(self.base.start, lo), months_of_slack=lo, p_with_plan=round(p_plan, 3))

    def rank(self, candidates: list[LeverImpact], fixed_impacts: list[LeverImpact] | None = None) -> list[LeverScore]:
        fixed_impacts = fixed_impacts or []
        base_out = self.outcome(fixed_impacts)
        T_end = months_between(self.base.start, base_out.achieved.horizon_end)
        tidx = months_between(self.base.start, base_out.target_date)

        def idx(o: GoalOutcome) -> int:
            return months_between(self.base.start, o.achieved.p50) if o.achieved.p50 else T_end + 1

        scores = []
        for lv in candidates:
            o = self.outcome(fixed_impacts + [lv])
            gained = idx(base_out) - idx(o)
            scores.append(LeverScore(
                lever_id=lv.lever_id, months_gained=gained if (o.achieved.p50 or base_out.achieved.p50) else None,
                delta_p=round(o.p_success - base_out.p_success, 3), p_success=o.p_success, achieved_p50=o.achieved.p50,
                monthly_equivalent=round(lv.headline_monthly if lv.headline_monthly is not None
                                         else monthly_equivalent(lv, self.base.start, tidx, self.base.salary_net_monthly), 0),
            ))
        scores.sort(key=lambda s: (-(s.months_gained or 0), -s.delta_p))
        return scores

    def auto_plan(self, candidates: list[LeverImpact], effort_weight: dict[str, float],
                  fixed_impacts: list[LeverImpact] | None = None, max_levers: int = 6,
                  weight_multiplier: dict[str, float] | None = None) -> list[str]:
        """Greedy: add the lever with the best progress per unit of effort until the goal is on track.

        weight_multiplier penalises levers with hidden costs (e.g. pillar 2 withdrawals hurt retirement).
        """
        fixed_impacts = fixed_impacts or []
        weight_multiplier = weight_multiplier or {}
        chosen: list[LeverImpact] = []
        score_now = self.progress(fixed_impacts)
        pool = list(candidates)
        while self.p_success(fixed_impacts + chosen) < self.threshold and pool and len(chosen) < max_levers:
            excluded = {e for c in chosen for e in c.excludes} | {c.lever_id for c in chosen}
            best, best_value, best_score = None, 0.0, score_now
            for lv in pool:
                if lv.lever_id in excluded or any(c.lever_id in lv.excludes for c in chosen):
                    continue
                s = self.progress(fixed_impacts + chosen + [lv])
                weight = effort_weight.get(lv.effort, 1.0) * weight_multiplier.get(lv.lever_id, 1.0)
                value = (s - score_now) / weight
                if value > best_value + 1e-9:
                    best, best_value, best_score = lv, value, s
            if best is None or best_score - score_now < 0.002:
                break
            chosen.append(best)
            pool.remove(best)
            score_now = best_score
        return [c.lever_id for c in chosen]


__all__ = ["Planner", "GoalOutcome", "Deadline", "LeverScore", "DateBand", "FanChart", "apply_goal_changes",
           "monthly_equivalent", "GoalChange"]
