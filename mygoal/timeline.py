"""All confirmed goals on one timeline: what the client has over time when every goal happens at its date.

Spending goals (a home, a car, a trip) take their money out at their date. Saving goals ("have X set aside": an
education fund, an emergency fund) keep it but lock it, and pension money (pillars 2 and 3a) is locked by law; both
show in their own colors, and every drop or lock is a vertical step at the goal date.

Only *accepted* actions change the chart and the chances. For a goal at risk (chance of failing above
`app.planning.alert_failure`) there is a proposal (the engine's standard plan plus the AI's ideas); the client's current
selection of it is previewed (`preview`: goal id -> action ids) without touching the chart until they accept it.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from .engine import simulate
from .explain.translate import tr
from .goals import GOALS, parse_params, target_date
from .model import GoalSpec, LeverImpact, add_months, months_between

if TYPE_CHECKING:
    from .service import PlanningService


def kind(g: GoalSpec) -> str:
    if g.type == "retirement":
        return "retirement"
    return str(g.params.get("kind", "spend")) if g.type == "target" else "spend"


def amount(g: GoalSpec) -> float | None:
    v = g.params.get("price") if g.type == "home" else g.params.get("amount")
    return float(v) if v is not None else None


def june(d: date) -> date:
    """Goal dates are June 1: the first June on or after d."""
    return date(d.year, 6, 1) if d <= date(d.year, 6, 1) else date(d.year + 1, 6, 1)


def _commit(g: GoalSpec, base, cfg, when: date) -> LeverImpact | None:
    plugin = GOALS.get(g.type)
    return plugin.commitment(g, parse_params(plugin, g), base, cfg, when)


def _shortfall(pl, impacts: list[LeverImpact], when: date) -> float:
    """Expected shortfall at the goal date (today's CHF): the average gap, counting the futures that make it as 0."""
    tidx = months_between(pl.base.start, when)
    if tidx <= 0:
        return 0.0
    _, _, traj, ev = pl._evaluate(impacts, T=tidx)
    gap = np.maximum(np.asarray(ev.need)[tidx] - np.asarray(ev.have)[tidx], 0) / np.asarray(traj.price)[tidx]
    return round(float(gap.mean()), -2)


def _card(svc: "PlanningService", lv: LeverImpact, lang: str) -> dict[str, Any]:
    """A lever card without ranking (for accepted actions of goals that are fine): enough for the list and Details."""
    return {"lever_id": lv.lever_id, "title": svc.lever_title(lv, lang), "description": tr(lv.description, lang), "group": lv.group,
            "effort": lv.effort, "confidence": lv.confidence, "side_effects": [tr(x, lang) for x in lv.side_effects],
            "product_trigger": lv.product_trigger, "icon": lv.icon,
            "origin": lv.origin, "details": lv.details, "assumptions": [svc.view(a, lang).model_dump(mode="json") for a in lv.assumptions],
            "months_gained": None, "delta_p": 0.0, "monthly_equivalent": 0.0, "impact_label": "", "active": False,
            "in_plan": False, "helps": True, "trade_off": False, "rank": None}


def build(svc: "PlanningService", client_id: str, active: list[str], overrides: dict, lang: str = "en",
          preview: dict[str, list[str]] | None = None, listed: list[str] | None = None) -> dict[str, Any]:
    from .service import PlanRequest
    st = svc.state(client_id)
    cfg = svc.cfg
    glob = overrides.get("global", {})
    preview = preview or {}
    alert = float(cfg.get_path("app.planning.alert_failure", 0.10))
    items = []
    for g in (g for g in st.goals if g.status == "confirmed"):
        pl = svc.planner(client_id, g, glob)
        items.append((target_date(GOALS.get(g.type), g, pl.base), g, pl))
    items.sort(key=lambda x: x[0])

    rows, cards, levers_by_id = [], {}, {}
    for k, (when, g, pl) in enumerate(items):
        by_id = {lv.lever_id: lv for lv in svc.levers(client_id, g, pl.base, overrides)}
        for i, lv in by_id.items():
            levers_by_id.setdefault(i, lv)
        act = [by_id[i] for i in active if i in by_id]
        prior = [c for w, h, _ in items[:k] if (c := _commit(h, pl.base, cfg, w)) is not None]   # earlier goals, paid
        p_base = pl.p_success(prior)
        p_now = pl.p_success(prior + act) if act else p_base
        row: dict[str, Any] = {
            "id": g.id, "label": svc.goal_label(g, lang), "type": g.type, "kind": kind(g), "date": when, "amount": amount(g),
            "retirement_age": g.params.get("retirement_age"), "p_base": round(p_base, 3), "p": round(p_now, 3),
            "at_risk": (1 - p_base) > alert or (1 - p_now) > alert, "shortfall": None,
            "proposal": [], "p_proposal": None, "p_preview": None, "shortfall_preview": None, "move_to": None,
        }
        if (1 - p_now) > alert:
            row["shortfall"] = _shortfall(pl, prior + act, when)
        if row["at_risk"]:
            plan = svc.plan(client_id, PlanRequest(goal_id=g.id, active=active, overrides=overrides, lang=lang,
                                                    include_cross_goal=False))
            ideas = [i for i in st.ai_ideas.get(g.id, []) if i in by_id]
            proposal = list(dict.fromkeys([*plan.plan, *ideas]))
            row["proposal"] = proposal
            row["p_proposal"] = round(pl.p_success(prior + [by_id[i] for i in dict.fromkeys([*proposal, *active]) if i in by_id]), 3)
            chosen = [i for i in preview.get(g.id, []) if i in by_id and i not in active]
            if chosen:                                    # what accepting the current selection would do
                impacts = prior + act + [by_id[i] for i in chosen]
                row["p_preview"] = round(pl.p_success(impacts), 3)
                row["shortfall_preview"] = _shortfall(pl, impacts, when) if 1 - row["p_preview"] > alert else 0.0
            for c in plan.levers:
                cards[c.lever_id] = c.model_dump(mode="json")
            later = pl.outcome(prior + act).achieved.p90   # 9 of 10 futures have made it by then
            if later is not None and later > when:
                later = june(later)
                row["move_to"] = {"date": later, "retirement_age": round(pl.base.age_at(later)) if g.type == "retirement" else None}
        rows.append(row)
    wanted = set(active) | set(listed or []) | {i for ids in preview.values() for i in ids} | {i for r in rows for i in r["proposal"]}
    for i in wanted:
        if i not in cards and i in levers_by_id:
            cards[i] = _card(svc, levers_by_id[i], lang)

    chart = _chart(svc, client_id, items, [levers_by_id[i] for i in active if i in levers_by_id], glob)
    return {**chart, "goals": rows, "cards": {i: c for i, c in cards.items() if i in wanted}, "alert_failure": alert}


def _chart(svc: "PlanningService", client_id: str, items, act: list[LeverImpact], glob: dict) -> dict[str, Any]:
    """One simulation with every spending goal paid at its date (accepted actions only): free, locked, pension."""
    if items:
        pl = items[0][2]
        base, market, N, seed = pl.base, pl.market, pl.N, pl.seed
    else:
        base, market, _ = svc.baseline(client_id, glob)
        sim = svc.cfg["app"]["simulation"]
        N, seed = sim["n_paths"], sim["seed"]
    cfg = svc.cfg
    dated = [w for w, g, _ in items if g.type != "retirement"]
    retire = [w for w, g, _ in items if g.type == "retirement"]
    end = add_months(max(dated), 36) if dated else add_months(min(retire), 12) if retire else add_months(base.start, 60)
    T = int(np.clip(months_between(base.start, end), 24, 12 * cfg["app"]["simulation"]["max_horizon_years"]))
    spend = [c for w, g, _ in items if kind(g) == "spend" and (c := _commit(g, base, cfg, w)) is not None]
    traj = simulate(base, act + spend, market, T, N, seed)
    free = np.asarray(traj.cash) + np.asarray(traj.invested)
    pension = np.median(np.asarray(traj.p3a) + np.asarray(traj.p2), axis=1)
    price = np.median(np.asarray(traj.price), axis=1)
    med, low = np.median(free, axis=1), np.percentile(free, 10, axis=1)
    locked = np.zeros(T + 1)
    steps = set()
    for w, g, _ in items:
        i0 = months_between(base.start, w)
        if 0 <= i0 < T and g.type != "retirement":
            steps.add(i0)
            if kind(g) == "save" and amount(g):
                locked[i0 + 1:] += amount(g) * price[i0 + 1:]
    # quarterly points, plus each goal date twice (before / just after) so drops and locks are vertical
    points = [(traj.date_at(i), i) for i in range(0, T + 1, 3) if i not in steps and i - 1 not in steps]
    points += [(traj.date_at(i), i) for i in steps] + [(traj.date_at(i) + timedelta(days=1), i + 1) for i in steps]
    points.sort()
    return {
        "dates": [d for d, _ in points],
        "free": [round(float(med[i])) for _, i in points],
        "free_low": [round(float(low[i])) for _, i in points],
        "locked": [round(float(min(locked[i], max(med[i], 0)))) for _, i in points],
        "pension": [round(float(pension[i])) for _, i in points],
        "start": base.start, "end": traj.date_at(T),
    }
