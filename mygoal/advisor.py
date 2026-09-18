"""Advisor view: the same numbers framed as a conversation agenda with product triggers.

This is where life goals become structured, proactive triggers for the bank (mortgage pre-check, 3a, investment
plan, partner referrals), instead of reactive cross-selling. Kept visually and logically separate from client advice.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .explain import chf, month
from .model import add_months

if TYPE_CHECKING:
    from .service import PlanningService

PRODUCTS = {
    "mortgage": {"en": "Mortgage pre-check", "de": "Hypotheken-Vorabklärung"},
    "3a": {"en": "Pillar 3a account or fund", "de": "Säule-3a-Konto oder -Fonds"},
    "investment_plan": {"en": "Investment plan / portfolio", "de": "Anlageplan / Portfolio"},
    "health_insurance": {"en": "Health insurance check (partner)", "de": "Krankenkassen-Check (Partner)"},
}


def _fmt(value: float, unit: str) -> str:
    if unit == "share" or unit.startswith("%"):
        return f"{value:.0%}"
    if unit.startswith("CHF"):
        return chf(value) + unit[3:]
    return f"{value:,.0f} {unit}".replace(",", "'")


def advisor_agenda(svc: "PlanningService", client_id: str, goal_id: str | None, lang: str = "en") -> dict[str, Any]:
    from .service import PlanRequest
    st = svc.state(client_id)
    p = st.profile
    goal = svc.goal(client_id, goal_id) if goal_id else st.goals[0]
    plan = svc.plan(client_id, PlanRequest(goal_id=goal.id, lang=lang, include_cross_goal=False))
    helpful = sorted([c for c in plan.levers if c.helps and c.group != "life_event" and c.rank is not None],
                     key=lambda c: (not c.in_plan, c.rank))

    questions: list[dict] = []
    seen: set[str] = set()
    for a in [*plan.assumptions, *(a for c in helpful[:5] for a in c.assumptions)]:
        if a.needs_confirmation and a.label not in seen:
            seen.add(a.label)
            questions.append({"topic": a.label, "we_assumed": _fmt(a.value, a.unit), "source": a.source})
    if p.opaque_share >= 0.1:
        questions.append({"topic": "Opaque spending" if lang == "en" else "Nicht zuordenbare Ausgaben",
                          "we_assumed": f"{chf(p.opaque_monthly)}/month in cash, TWINT and card bills",
                          "source": "transactions"})
    for note in p.data_quality:
        if note.level == "warning":
            questions.append({"topic": "Data", "we_assumed": note.message, "source": "transactions"})

    triggers = []
    base = svc.planner(client_id, goal, {}).base
    for c in helpful:
        if not c.product_trigger:
            continue
        timing, volume = "", None
        if c.product_trigger == "3a":
            timing = "before 31 Dec" if lang == "en" else "vor dem 31. Dez."
            volume = 12 * c.assumptions[0].value if c.assumptions else None
        elif c.product_trigger == "investment_plan":
            timing = "now" if lang == "en" else "jetzt"
            volume = next((a.value for a in c.assumptions if a.key == "amount"), None)
        elif c.product_trigger == "health_insurance":
            timing = "before 30 Nov" if lang == "en" else "vor dem 30. Nov."
        triggers.append({"product": c.product_trigger, "label": PRODUCTS.get(c.product_trigger, {}).get(lang, c.product_trigger),
                         "reason": c.title, "impact": c.impact_label, "timing": timing, "volume": volume, "lever_id": c.lever_id})
    if goal.type == "home":
        when = plan.scenario.achieved.p50 or plan.baseline.target_date
        price = float(goal.params.get("price", 0))
        triggers.insert(0, {"product": "mortgage", "label": PRODUCTS["mortgage"][lang], "reason": goal.label,
                            "impact": plan.texts["headline"], "timing": month(add_months(min(when, plan.baseline.target_date), -12), lang),
                            "volume": round(0.8 * price), "lever_id": None})

    unique, seen_products = [], set()
    for trig in triggers:
        if trig["product"] not in seen_products:
            seen_products.add(trig["product"])
            unique.append(trig)
    triggers = unique

    return {
        "client": {"name": st.ds.client.name, "age": p.age, "canton": st.ds.client.canton,
                   "gross_income": round(p.income.gross_annual), "liquid": round(p.balances.liquid),
                   "invested": round(p.balances.invested), "p3a": round(p.balances.p3a), "p2": round(p.balances.p2),
                   "fcf_monthly": round(p.free_cash_flow_monthly), "savings_rate": p.savings_rate},
        "goal": goal.model_dump(mode="json"),
        "headline": plan.texts["headline"], "gap": plan.texts["gap"], "deadline": plan.texts["deadline"],
        "plan": plan.texts["plan"], "drivers": plan.drivers,
        "top_levers": [{"lever_id": c.lever_id, "title": c.title, "impact": c.impact_label, "monthly": c.monthly_equivalent,
                        "effort": c.effort, "trade_off": c.trade_off, "side_effects": c.side_effects} for c in helpful[:3]],
        "open_questions": questions[:8],
        "product_triggers": triggers,
        "base_start": base.start,
    }
