"""All confirmed goals on one timeline: what the client has over time when every goal happens at its date.

Spending goals (a home, a car, a trip) take their money out at their date. Saving goals ("have X set aside": an
education fund, an emergency fund) keep it but lock it, and pension money (pillars 2 and 3a) is locked by law; both
show in their own colors, and every drop or lock is a vertical step at the goal date.

Actions are simply on or off (`active`). Moving a goal later is an action too (`move:<goal id>:<date>`). One goal is in
focus: the first one failing in more than `app.planning.alert_failure` of futures (or the one the client picked). For it
the timeline lists the recommended actions (the engine's plan plus the AI's ideas) and, for every listed action, how
many points it adds to that goal's chance of success.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np

from .engine import simulate
from .explain import t
from .explain.translate import tr
from .goals import GOALS, parse_params, target_date
from .model import GoalSpec, LeverImpact, add_months, months_between

if TYPE_CHECKING:
    from .service import PlanningService

MOVE = "move:"


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


def move_id(goal_id: str, when: date) -> str:
    return f"{MOVE}{goal_id}:{when.isoformat()}"


def moves_of(ids) -> dict[str, date]:
    out = {}
    for i in ids:
        if i.startswith(MOVE):
            gid, _, iso = i[len(MOVE):].rpartition(":")
            out[gid] = date.fromisoformat(iso)
    return out


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
    """A lever card without ranking: enough for the list and the Details drawer."""
    return {"lever_id": lv.lever_id, "title": svc.lever_title(lv, lang), "description": tr(lv.description, lang), "group": lv.group,
            "effort": lv.effort, "confidence": lv.confidence, "side_effects": [tr(x, lang) for x in lv.side_effects],
            "product_trigger": lv.product_trigger, "icon": lv.icon,
            "origin": lv.origin, "details": lv.details, "assumptions": [svc.view(a, lang).model_dump(mode="json") for a in lv.assumptions],
            "months_gained": None, "delta_p": 0.0, "monthly_equivalent": 0.0, "impact_label": "", "active": False,
            "in_plan": False, "helps": True, "trade_off": False, "rank": None}


def build(svc: "PlanningService", client_id: str, active: list[str], overrides: dict, lang: str = "en",
          focus: str | None = None, listed: list[str] | None = None) -> dict[str, Any]:
    from .service import PlanRequest
    st = svc.state(client_id)
    cfg = svc.cfg
    glob = overrides.get("global", {})
    alert = float(cfg.get_path("app.planning.alert_failure", 0.10))
    confirmed = [g for g in st.goals if g.status == "confirmed"]
    ids = {g.id for g in confirmed}
    act_ids = [i for i in active if not i.startswith(MOVE)]
    moves = {k: v for k, v in moves_of(active).items() if k in ids}

    def items_for(mv: dict[str, date]):
        out = []
        for g in confirmed:
            spec = g
            if g.id in mv:
                if g.type == "retirement":
                    age = round(svc.planner(client_id, g, glob).base.age_at(mv[g.id]))
                    spec = g.model_copy(update={"params": {**g.params, "retirement_age": age}})
                else:
                    spec = g.model_copy(update={"target_date": mv[g.id]})
            pl = svc.planner(client_id, spec, glob)
            out.append((target_date(GOALS.get(spec.type), spec, pl.base), spec, pl))
        return sorted(out, key=lambda x: x[0])

    levers: dict[str, dict[str, LeverImpact]] = {}

    def levers_of(g: GoalSpec, pl) -> dict[str, LeverImpact]:
        if g.id not in levers:
            levers[g.id] = {lv.lever_id: lv for lv in svc.levers(client_id, g, pl.base, overrides)}
        return levers[g.id]

    def chance(items, gid: str, lever_ids):
        """P(goal gid succeeds) with the goals before it paid and these actions on; also its impacts, planner, date."""
        k = next(i for i, (_, g, _) in enumerate(items) if g.id == gid)
        when, g, pl = items[k]
        by_id = levers_of(g, pl)
        prior = [c for w, h, _ in items[:k] if (c := _commit(h, pl.base, cfg, w)) is not None]
        impacts = prior + [by_id[i] for i in lever_ids if i in by_id]
        return pl.p_success(impacts), impacts, pl, when

    items, plain = items_for(moves), items_for({})
    rows = []
    for when, g, pl in items:
        p_now, impacts, _, _ = chance(items, g.id, act_ids)
        p_base = chance(plain, g.id, [])[0]
        row: dict[str, Any] = {
            "id": g.id, "label": svc.goal_label(g, lang), "type": g.type, "kind": kind(g), "date": when, "amount": amount(g),
            "retirement_age": g.params.get("retirement_age"), "p_base": round(p_base, 3), "p": round(p_now, 3),
            "at_risk": (1 - p_base) > alert or (1 - p_now) > alert, "moved": g.id in moves,
            "shortfall": _shortfall(pl, impacts, when) if (1 - p_now) > alert else None, "move_to": None,
        }
        if (1 - p_now) > alert and g.id not in moves:
            later = pl.outcome(impacts).achieved.p90       # 9 of 10 futures have made it by then
            if later is not None and later > when:
                later = june(later)
                row["move_to"] = {"date": later, "action": move_id(g.id, later),
                                  "retirement_age": round(pl.base.age_at(later)) if g.type == "retirement" else None}
        rows.append(row)

    failing = [r["id"] for r in rows if r["at_risk"]]
    focus_id = focus if focus in failing else (failing[0] if failing else None)
    cards: dict[str, dict] = {}
    actions = None
    if focus_id:
        plan = svc.plan(client_id, PlanRequest(goal_id=focus_id, active=act_ids, overrides=overrides, lang=lang,
                                                include_cross_goal=False))
        fwhen, fg, fpl = next(x for x in items if x[1].id == focus_id)
        by_id = levers_of(fg, fpl)
        ideas = [i for i in st.ai_ideas.get(focus_id, []) if i in by_id]
        recommended = [i for i in dict.fromkeys([*plan.plan, *ideas]) if i not in act_ids]
        for c in plan.levers:
            cards[c.lever_id] = c.model_dump(mode="json")
        p_now = chance(items, focus_id, act_ids)[0]
        gains = {}
        for i in dict.fromkeys([*recommended, *(listed or []), *active]):
            if i.startswith(MOVE):
                mv = {k: v for k, v in moves_of([i]).items() if k in ids}
                if not mv:
                    continue
                gid = next(iter(mv))
                with_mv, without_mv = {**moves, **mv}, {k: v for k, v in moves.items() if k != gid}
                gains[i] = chance(items_for(with_mv), focus_id, act_ids)[0] - chance(items_for(without_mv), focus_id, act_ids)[0]
                g = next(x for x in confirmed if x.id == gid)
                cards[i] = {**_card(svc, LeverImpact(lever_id=i, title="", group="goal_change", effort="medium", icon="calendar"), lang),
                            "title": t("actions.move", lang, label=svc.goal_label(g, lang), year=mv[gid].year), "origin": "user"}
            elif i in by_id:
                on = [x for x in act_ids if x != i]
                gains[i] = chance(items, focus_id, [*on, i])[0] - chance(items, focus_id, on)[0]
                cards.setdefault(i, _card(svc, by_id[i], lang))
        actions = {"goal_id": focus_id, "goal_label": svc.goal_label(fg, lang), "goal_date": fwhen, "recommended": recommended,
                   "gains": {k: round(v, 3) for k, v in gains.items()},
                   "p_from": round(chance(plain, focus_id, [])[0], 3), "p_to": round(p_now, 3)}
    for i in act_ids:                                     # active actions of goals that are fine still need a card
        if i not in cards:
            for by_id in levers.values():
                if i in by_id:
                    cards[i] = _card(svc, by_id[i], lang)
                    break

    all_levers = {i: lv for by_id in levers.values() for i, lv in by_id.items()}
    chart = _chart(svc, client_id, items, [all_levers[i] for i in act_ids if i in all_levers], glob)
    return {**chart, "goals": rows, "actions": actions, "cards": cards, "alert_failure": alert,
            "success_threshold": float(cfg.get_path("app.simulation.success_threshold", 0.7))}


def _chart(svc: "PlanningService", client_id: str, items, act: list[LeverImpact], glob: dict) -> dict[str, Any]:
    """One simulation with every spending goal paid at its date (active actions only): free, locked, pension."""
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
