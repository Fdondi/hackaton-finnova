"""All confirmed goals on one timeline: what the client has over time when every goal happens at its date.

Spending goals (a home, a car, a trip) take their money out at their date. Saving goals ("have X set aside": an
education fund, an emergency fund) keep it but lock it, and pension money (pillars 2 and 3a) is locked by law; both
show in their own colors. Each goal's chance counts the goals before it as already paid, plus the ticked actions.
A goal whose chance of failing is above `app.planning.alert_failure` gets a proposal: the engine's standard plan plus
the AI's ad-hoc ideas for it, the chance with them, and the date by which 9 of 10 futures would make it.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

import numpy as np

from .engine import simulate
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


def _commit(g: GoalSpec, base, cfg, when: date) -> LeverImpact | None:
    plugin = GOALS.get(g.type)
    return plugin.commitment(g, parse_params(plugin, g), base, cfg, when)


def build(svc: "PlanningService", client_id: str, active: list[str], overrides: dict, lang: str = "en") -> dict[str, Any]:
    from .service import PlanRequest
    st = svc.state(client_id)
    cfg = svc.cfg
    glob = overrides.get("global", {})
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
            "id": g.id, "label": g.label, "type": g.type, "kind": kind(g), "date": when, "amount": amount(g),
            "retirement_age": g.params.get("retirement_age"), "p_base": round(p_base, 3), "p": round(p_now, 3),
            "at_risk": (1 - p_base) > alert or (1 - p_now) > alert, "proposal": [], "p_proposal": None, "move_to": None,
        }
        if row["at_risk"]:
            plan = svc.plan(client_id, PlanRequest(goal_id=g.id, active=active, overrides=overrides, lang=lang,
                                                    include_cross_goal=False))
            ideas = [i for i in st.ai_ideas.get(g.id, []) if i in by_id]
            proposal = list(dict.fromkeys([*plan.plan, *ideas]))
            row["proposal"] = proposal
            with_prop = [by_id[i] for i in dict.fromkeys([*proposal, *active]) if i in by_id]
            row["p_proposal"] = round(pl.p_success(prior + with_prop), 3)
            for c in plan.levers:
                if c.lever_id in set(proposal) | set(active):
                    cards[c.lever_id] = c.model_dump(mode="json")
            out = pl.outcome(prior + act)
            later = out.achieved.p90                      # 9 of 10 futures have made it by then
            if later is not None and later > when:
                row["move_to"] = {"date": later, "retirement_age": round(pl.base.age_at(later)) if g.type == "retirement" else None}
        rows.append(row)
    for i in active:                                      # cards for ticked actions of goals that are fine
        if i not in cards and i in levers_by_id:
            lv = levers_by_id[i]
            cards[i] = {"lever_id": i, "title": lv.title, "description": lv.description, "group": lv.group, "effort": lv.effort,
                        "origin": lv.origin, "icon": lv.icon, "impact_label": "", "monthly_equivalent": 0.0, "assumptions": [],
                        "confidence": lv.confidence, "side_effects": lv.side_effects, "months_gained": None, "delta_p": 0.0}

    chart = _chart(svc, client_id, items, [levers_by_id[i] for i in active if i in levers_by_id], glob)
    return {**chart, "goals": rows, "cards": cards, "alert_failure": alert}


def _chart(svc: "PlanningService", client_id: str, items, act: list[LeverImpact], glob: dict) -> dict[str, Any]:
    """One simulation with every spending goal paid at its date: free money, locked savings goals, pension."""
    if items:
        pl = items[0][2]
        base, market = pl.base, pl.market
    else:
        base, market, _ = svc.baseline(client_id, glob)
        pl = None
    cfg = svc.cfg
    dated = [w for w, g, _ in items if g.type != "retirement"]
    retire = [w for w, g, _ in items if g.type == "retirement"]
    end = max(dated) if dated else (min(retire) if retire else add_months(base.start, 60))
    end = add_months(end, 36 if dated else 12)
    T = int(np.clip(months_between(base.start, end), 24, 12 * cfg["app"]["simulation"]["max_horizon_years"]))
    spend = [c for w, g, _ in items if kind(g) == "spend" and (c := _commit(g, base, cfg, w)) is not None]
    sim = cfg["app"]["simulation"]
    traj = simulate(base, act + spend, market, T, pl.N if pl else sim["n_paths"], pl.seed if pl else sim["seed"])
    free = traj.cash + traj.invested
    pension = traj.p3a + traj.p2
    price = np.median(traj.price, axis=1)
    idx = sorted(set(range(0, T + 1, 3)) | {months_between(base.start, w) for w, _, _ in items if months_between(base.start, w) <= T})
    locked = np.zeros(T + 1)
    for w, g, _ in items:
        if kind(g) == "save" and amount(g):
            i0 = months_between(base.start, w)
            if 0 <= i0 <= T:
                locked[i0:] += amount(g) * price[i0:]
    med = np.median(free, axis=1)
    return {
        "dates": [traj.date_at(i) for i in idx],
        "free": [round(float(med[i])) for i in idx],
        "free_low": [round(float(np.percentile(free[i], 10))) for i in idx],
        "locked": [round(float(min(locked[i], max(med[i], 0)))) for i in idx],
        "pension": [round(float(np.median(pension[i]))) for i in idx],
        "start": base.start, "end": traj.date_at(T),
    }
