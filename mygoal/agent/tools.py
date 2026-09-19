"""Tools shared by the LLM agent and the rules agent. They read the client's data and build levers;
they never let anyone type a bare number into the engine."""
from __future__ import annotations

import json
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import BaseModel, ValidationError

from ..levers import PRIMITIVES
from ..levers.primitives import Estimate
from ..llm import ToolSpec
from .session import Session

if TYPE_CHECKING:
    from ..service import PlanningService


@lru_cache(maxsize=1)
def vocabulary() -> dict:
    return yaml.safe_load((Path(__file__).parent / "keywords.yaml").read_text(encoding="utf-8"))


def expand_terms(query: str) -> list[str]:
    vocab = vocabulary()
    words = [w for w in re.split(r"[^\wäöüéèà&]+", query.lower()) if len(w) > 2 and w not in vocab["stopwords"]]
    terms = set(words)
    for key, syns in vocab["synonyms"].items():
        if key in words or any(s in query.lower() for s in syns):
            terms |= set(syns) | {key}
    return sorted(terms)


def search_transactions(svc: "PlanningService", client_id: str, query: str) -> dict[str, Any]:
    st = svc.state(client_id)
    terms = expand_terms(query)
    if not terms:
        return {"query": query, "terms": [], "matches": [], "monthly_last_12m": 0.0, "total": 0.0}
    window_start = st.profile.window_start
    groups: dict[str, dict] = {}
    for b in st.ds.bookings:
        hay = " ".join([b.text, b.counterparty or "", b.merchant or "", " ".join(b.tags), b.category or ""]).lower()
        if not any(t in hay for t in terms) or b.category == "internal_transfer":
            continue
        g = groups.setdefault(b.merchant or "unknown", {"merchant": b.merchant, "category": b.category, "tags": set(),
                                                         "count": 0, "total": 0.0, "last_12m": 0.0, "first": b.booking_date,
                                                         "last": b.booking_date, "example": b.text})
        g["count"] += 1
        g["total"] += b.amount
        g["tags"] |= set(b.tags)
        g["first"], g["last"] = min(g["first"], b.booking_date), max(g["last"], b.booking_date)
        if b.booking_date >= window_start:
            g["last_12m"] += b.amount
    recurring = {r.merchant: r for r in st.profile.recurring if r.active}
    matches = []
    for g in sorted(groups.values(), key=lambda g: g["total"]):
        r = recurring.get(g["merchant"])
        matches.append({**g, "tags": sorted(g["tags"]), "first": g["first"].isoformat(), "last": g["last"].isoformat(),
                        "total": round(g["total"], 2), "last_12m": round(g["last_12m"], 2),
                        "cadence": r.period_label if r else "irregular"})
    covered = max(st.profile.covered_months, 1)
    return {"query": query, "terms": terms, "matches": matches[:10],
            "monthly_last_12m": round(-sum(m["last_12m"] for m in matches) / covered, 2),
            "total": round(sum(m["total"] for m in matches), 2), "history_months": st.profile.history_months}


def profile_summary(svc: "PlanningService", client_id: str, goal_id: str) -> dict[str, Any]:
    st = svc.state(client_id)
    p = st.profile
    goal = svc.goal(client_id, goal_id)
    return {
        "age": p.age, "canton": st.ds.client.canton, "household": st.ds.client.household.model_dump(),
        "net_income_monthly": round(p.income.salary_net_monthly_avg + p.income.other_income_monthly),
        "gross_income_annual": round(p.income.gross_annual), "spending_monthly": round(p.spending_monthly),
        "free_cash_flow_monthly": round(p.free_cash_flow_monthly), "liquid": round(p.balances.liquid),
        "invested": round(p.balances.invested), "pillar3a": round(p.balances.p3a), "pillar2": round(p.balances.p2),
        "top_spending": [{"category": f.category, "monthly": round(f.monthly)} for f in p.flows if f.kind == "spending"][:10],
        "hints": [{"kind": h.kind, "label": h.label, "monthly_cost": round(h.monthly_cost), "evidence": h.evidence[:4]} for h in p.hints],
        "goal": goal.model_dump(mode="json"),
    }


LIFE_EVENTS = {"birth": "have_child", "marriage": "wedding", "divorce": "separation", "job_change": "job_change",
               "migration": None, "income": None}
EVENT_ALIASES = {"baby": "birth", "child": "birth", "wedding": "marriage", "separation": "divorce", "new_job": "job_change",
                 "job": "job_change", "moving": "migration", "move": "migration", "inheritance": "income"}


def life_event_evidence(svc: "PlanningService", event: str) -> dict[str, Any]:
    """What happened to people in the bank's population data after a life event (see mygoal/population.py)."""
    pop = svc.services.get("population")
    name = EVENT_ALIASES.get(event, event)
    ev = pop.life_event(name) if pop is not None else None
    if ev is None:
        return {"event": name, "available": False,
                "note": "No population evidence for this event: use the client's data or labelled estimates."}
    c = ev.get("event_costs") or {}
    out = {
        "event": name, "available": True, "people": ev["n"],
        "monthly_spending_change": {k: ev["d_spend"][k] for k in ("median", "iqr", "ci90")},
        "monthly_salary_change": {k: ev["d_salary"][k] for k in ("median", "iqr", "ci90")},
        "costs_around_the_event": {"share_of_events_with_costs": c.get("share_with_costs"), "median_if_any": c.get("median_if_any"),
                                   "iqr_if_any": c.get("iqr_if_any"),
                                   "typical_items": [v["vendor"] for v in c.get("top_vendors", [])][:3]},
        "categories_that_moved": ev.get("categories", []),
        "method": "per person, 4 months after vs 4 months before the event, adjusted for seasonality (CHF/month)",
        "ready_made_lever": LIFE_EVENTS.get(name),
        "source_label": "population",
    }
    if name == "job_change" and ev.get("income_ratio"):
        r = ev["income_ratio"]
        out["salary_after_job_change"] = {k: r[k] for k in ("n", "median_change_pct", "share_cut", "cut_median_pct",
                                                            "p10_change_pct", "p90_change_pct")}
    return out


ESTIMATE_RULES = ("Estimate = {value: number, low?: number, high?: number, label: string, unit?: string, "
                  "source: transactions|user|market_default|llm_estimate|population}. Guesses need source llm_estimate with low and "
                  "high; numbers from life_event_evidence use source population.")


def primitive_catalogue(exclude: tuple[str, ...] = (), estimate_rules: str = ESTIMATE_RULES,
                        skip: tuple[str, ...] = ("side_effects",)) -> str:
    """Compact description of every primitive's parameters, for the LLM tool description (and the partner prompt)."""
    lines = []
    for name, d in PRIMITIVES.items():
        if name in exclude:
            continue
        fields = []
        for fname, f in d.params.model_fields.items():
            if fname in skip:
                continue
            ann = f.annotation
            typ = "Estimate" if ann is Estimate or "Estimate" in str(ann) else getattr(ann, "__name__", str(ann)).replace("typing.", "")
            desc = f" - {f.description}" if f.description else ""
            fields.append(f"    {fname}: {typ}{'' if f.is_required() else ' (optional)'}{desc}")
        lines.append(f"- {name}: {d.description}\n" + "\n".join(fields))
    return estimate_rules + "\n" + "\n".join(lines)


def tool_specs(max_questions: int) -> list[ToolSpec]:
    return [
        ToolSpec("get_profile_summary", "The client's income, spending by category, balances, detected assets and the goal being planned.",
                 {"type": "object", "properties": {}}),
        ToolSpec("search_transactions",
                 "Search the client's bookings by keywords (merchant names, themes like 'boat' or 'warhammer'; German and English). "
                 "Returns merchants with counts, totals, last-12-month sums and cadence.",
                 {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
        ToolSpec("life_event_evidence",
                 "What actually happened to people in the bank's data after a life event: how many people, the change in "
                 "monthly spending and salary, typical one-off costs (e.g. wedding, lawyers, hospital). Events: birth, "
                 "marriage, divorce, job_change, migration (moving canton), income (inheritance).",
                 {"type": "object", "properties": {"event": {"type": "string", "enum": [*LIFE_EVENTS, *EVENT_ALIASES]}},
                  "required": ["event"]}),
        ToolSpec("ask_user", f"Ask the client one short question (at most {max_questions} per what-if). Prefer numbers with a unit.",
                 {"type": "object", "properties": {
                     "question": {"type": "string"}, "kind": {"type": "string", "enum": ["number", "choice", "text"]},
                     "unit": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                     "min": {"type": "number"}, "max": {"type": "number"}, "default": {"type": "number"}},
                  "required": ["question", "kind"]}),
        ToolSpec("propose_lever",
                 "Build the what-if as one lever from primitives; returns its effect on the goal from the simulation engine. "
                 "Call again to revise. Primitives:\n" + primitive_catalogue(),
                 {"type": "object", "properties": {
                     "title": {"type": "string", "description": "Short action, e.g. 'Sell the boat'"},
                     "description": {"type": "string", "description": "One plain sentence for the client"},
                     "group": {"type": "string", "enum": ["no_lifestyle_cost", "structural", "behavioural", "goal_change", "life_event"]},
                     "effort": {"type": "string", "enum": ["none", "low", "medium", "high"]},
                     "parts": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": {
                         "primitive": {"type": "string", "enum": list(PRIMITIVES)}, "params": {"type": "object"}},
                         "required": ["primitive", "params"]}}},
                  "required": ["title", "parts"]}),
    ]


class LeverProposal(BaseModel):
    title: str
    description: str = ""
    group: str = "structural"
    effort: str = "medium"
    parts: list[dict[str, Any]]


def propose_lever(svc: "PlanningService", session: Session, args: dict[str, Any], created_by: str, prefix: str = "whatif",
                  **custom: Any) -> tuple[str, bool]:
    """Validate, register and evaluate a lever. Returns (message for the agent, is_error).
    `custom` goes to the CustomLever as is (e.g. source= for a partner's scenario)."""
    from ..service import CustomLever
    try:
        prop = LeverProposal.model_validate(args)
        problems = []
        for i, part in enumerate(prop.parts):
            d = PRIMITIVES.get(part.get("primitive", ""))
            params = {"title": prop.title, **part.get("params", {})}
            validated = d.params.model_validate(params)
            for fname in type(validated).model_fields:
                val = getattr(validated, fname)
                if isinstance(val, Estimate) and val.source == "llm_estimate" and (val.low is None or val.high is None):
                    problems.append(f"part {i} {fname}: an llm_estimate needs low and high")
            part["params"] = validated.model_dump(mode="json")
        if problems:
            return "Rejected: " + "; ".join(problems), True
    except (ValidationError, KeyError) as exc:
        return f"Rejected, invalid parameters: {exc}", True

    lever_id = session.lever_id or f"{prefix}:{uuid.uuid4().hex[:8]}"
    cl = CustomLever(lever_id=lever_id, title=prop.title, parts=prop.parts, created_by=created_by,
                     group=prop.group, effort=prop.effort, note=prop.description or None, **custom)
    try:
        svc.add_custom_lever(session.client_id, cl)
        evaluation = svc.evaluate_lever(session.client_id, session.goal_id, lever_id)
    except Exception as exc:
        svc.remove_custom_lever(session.client_id, lever_id)
        return f"Rejected, could not build the lever: {exc}", True
    session.lever_id = lever_id
    session.state["evaluation"] = evaluation
    return json.dumps({"lever_id": lever_id, "effect": {k: v for k, v in evaluation.items() if k != "assumptions"}}, default=str), False
