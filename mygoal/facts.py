"""Facts page: what we know about the client, what we assume, and what they told us, as one editable list.

Numbers come from the data and the assumption book (the same one the engine reads), never from the LLM. Edits map to:
  a:<key>      an assumption override (returned to the UI, which sends overrides with every plan request)
  h:adults / h:children   the household, stored on the client (life-event levers and specialists read it)
  n:<id>       a life fact in the client's words, passed to the LLM as context (goals, what-ifs)
The LLM reads the data back in plain words (`read`) and turns a chat message into edits (`chat`).
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from .agent.goal_assistant import _json, situation
from .explain import chf, t
from .explain.translate import tr
from .llm import get_llm

if TYPE_CHECKING:
    from .service import PlanningService

log = logging.getLogger("mygoal.facts")

FUTURE_KEYS = ["job_loss_prob", "buffer_months", "inflation", "real_wage_growth", "portfolio_return", "portfolio_volatility",
               "house_price_growth", "cash_rate"]


def fmt(value: float, unit: str) -> str:
    if unit == "share" or unit.startswith("%"):
        return f"{value:.1%}".replace(".0%", "%") + (unit[1:] if unit.startswith("%/") else "")
    if unit.startswith("CHF"):
        return chf(value) + unit[3:]
    return f"{value:,.1f}".rstrip("0").rstrip(".").replace(",", "'") + (f" {unit}" if unit else "")


def _fact(id: str, group: str, kind: str, label: str, display: str, lang: str, source: str | None = None, value: Any = None,
          unit: str = "", editable: bool = False, input: str = "none", note: str | None = None, **extra) -> dict[str, Any]:
    return {"id": id, "group": group, "kind": kind, "label": tr(label, lang), "display": tr(display, lang), "value": value,
            "unit": unit, "source": source, "source_label": t(f"sources.{source}", lang) if source else None,
            "editable": editable, "input": input, "note": tr(note, lang), **extra}


def build(svc: "PlanningService", client_id: str, overrides: dict | None = None, lang: str = "en") -> dict[str, Any]:
    st = svc.state(client_id)
    p, c, x = st.profile, st.ds.client, st.ds.client.extra
    base, market, assumptions = svc.baseline(client_id, (overrides or {}).get("global"))
    book = {a.key: a for a in assumptions}

    def from_book(key: str, group: str, label: str | None = None) -> dict | None:
        a = book.get(key)
        if a is None:
            return None
        kind = "yours" if a.source == "user" else "assumed" if a.source in ("market_default", "population", "llm_estimate") \
            or a.needs_confirmation else "known"
        return _fact(f"a:{key}", group, kind, label or a.label, fmt(a.value, a.unit), lang, a.source, a.value, a.unit,
                     a.editable, "number", a.note, low=a.low, high=a.high, step=a.step)

    # ---- money: in - out = free cash (the sketch's first box) ----
    bills = st.risk.bill_mean * market.bill_rate / 12 if st.risk is not None else 0.0   # expected one-off bills
    money_in = base.salary_net_monthly + base.other_income_monthly
    money_out = base.fixed_costs_monthly + base.variable_costs_monthly + bills

    def shown(f: dict | None, display: str | None = None, label: str | None = None) -> dict | None:
        if f is not None:
            f.update({k: tr(v, lang) for k, v in (("display", display), ("label", label)) if v is not None})
        return f

    money = [f for f in [
        from_book("salary_net_monthly", "money"),
        from_book("other_income_monthly", "money"),
        from_book("fixed_costs_monthly", "money"),
        from_book("variable_costs_monthly", "money"),
        shown(from_book("big_bill_rate", "money"),
              display=f"{market.bill_rate:.1f} × ~{chf(st.risk.bill_mean)} ≈ {chf(bills)}/month") if st.risk is not None else None,
        from_book("cash", "money"),
        from_book("invested", "money"),
        from_book("p3a_balance", "money"),
        from_book("pillar2_balance", "money"),
        from_book("gross_income_annual", "money"),
    ] if f]

    # ---- life: everything editable; master data changes rebuild the profile ----
    kids = c.household.children_birth_years
    hh_src = "user" if x.get("household_edited") else "client_data"
    cd = lambda field: "user" if field in x.get("edited", []) else "client_data"  # noqa: E731
    kind = lambda src: "yours" if src == "user" else "known"  # noqa: E731
    housing, car, p3a_pay = (book[k].value if k in book else 0.0 for k in ("housing_monthly", "car_monthly", "contrib_p3a_monthly"))
    life = [
        _fact("c:age", "life", kind(cd("age")), "Age", str(p.age), lang, cd("age"), p.age, "", True, "number", low=0, high=100, step=1),
        _fact("c:canton", "life", kind(cd("canton")), "Canton", (c.canton or "?") + (f" ({x['city']})" if x.get("city") else ""),
              lang, cd("canton"), c.canton or "", "", True, "text", "Two letters, e.g. ZH"),
        _fact("h:adults", "life", kind(hh_src), "Adults in the household", str(c.household.adults),
              lang, hh_src, c.household.adults, "", True, "number", "Married or living together counts as 2", low=1, high=2, step=1),
        _fact("h:children", "life", kind(hh_src), "Children", str(len(kids)) +
              (f" (born {', '.join(map(str, kids))})" if kids else ""), lang, hh_src, len(kids), "", True, "number",
              low=0, high=6, step=1),
        _fact("c:work", "life", kind(cd("work")), "Work", " · ".join(v for v in [
            str(x.get("employment_type") or "").replace("_", "-"), x.get("occupation") or "", x.get("sector") or ""] if v) or "?",
            lang, cd("work"), x.get("occupation") or "", "", True, "text"),
        shown(from_book("housing_monthly", "life"), label="Home",
              display=(("You own your home" if x.get("owns_property") else "You rent") + f": {chf(housing)}/month") if housing
              else ("You own your home" if x.get("owns_property") else "No housing costs seen")),
        shown(from_book("car_monthly", "life"), label="Car",
              display=f"You have a car: about {chf(car)}/month" if car > 1 else "No car costs seen"),
        shown(from_book("contrib_p3a_monthly", "life"), label="Pillar 3a",
              display=f"You pay {chf(p3a_pay)}/month into pillar 3a" if p3a_pay > 1 else "No pillar 3a payments seen"),
        _fact("c:interests", "life", kind(cd("interests")), "Interests", ", ".join(x.get("interests") or []) or "?", lang,
              cd("interests"), ", ".join(x.get("interests") or []), "", True, "text", "Comma separated"),
    ]
    life = [f for f in life if f]

    future = [f for f in (from_book(k, "future") for k in FUTURE_KEYS) if f]
    notes = [_fact(f"n:{n['id']}", "notes", "yours", "You told us", n["text"], lang, "user", n["text"], "", True, "text")
             for n in st.notes]
    return {
        "money": money, "life": life, "future": future, "notes": notes,
        "summary": {"money_in": round(money_in), "money_out": round(money_out), "free_cash": round(money_in - money_out)},
        "as_of": p.as_of, "data_notes": [{**n.model_dump(), "message": tr(n.message, lang)} for n in p.data_quality],
    }


def apply(svc: "PlanningService", client_id: str, fact_id: str, value: Any, overrides: dict | None) -> dict:
    """Apply one edit; returns the (possibly changed) overrides for the UI to keep."""
    st = svc.state(client_id)
    overrides = {k: dict(v) for k, v in (overrides or {}).items()}
    glob = overrides.setdefault("global", {})
    hh = st.ds.client.household
    if fact_id.startswith("a:"):
        key = fact_id[2:]
        if value in (None, ""):
            glob.pop(key, None)
        else:
            glob[key] = float(value)
        return overrides
    if fact_id.startswith("c:"):                       # master data: rebuild the profile, every number depends on it
        field_ = fact_id[2:]
        c, text = st.ds.client, str(value if value is not None else "").strip()
        if field_ == "age":
            c.birth_year = st.profile.as_of.year - max(0, min(int(float(text)), 110))
        elif field_ == "canton":
            c.canton = text.upper()[:2] or c.canton
        elif field_ == "work":
            c.extra["occupation"] = text
        elif field_ == "interests":
            c.extra["interests"] = [w.strip() for w in text.split(",") if w.strip()]
        else:
            raise ValueError(f"not editable: {fact_id}")
        c.extra["edited"] = sorted(set(c.extra.get("edited", [])) | {field_})
        svc.refresh_client(client_id)
        st.ai_facts.clear()
        return overrides
    if fact_id == "h:adults":
        hh.adults = max(1, min(int(float(value)), 2))
    elif fact_id == "h:children":
        n = max(0, min(int(float(value)), 8))
        years = list(hh.children_birth_years)
        hh.children_birth_years = years[:n] + [st.profile.as_of.year] * max(0, n - len(years))
    elif fact_id == "n:new":
        if str(value).strip():
            st.notes.append({"id": uuid.uuid4().hex[:6], "text": str(value).strip()[:300]})
    elif fact_id.startswith("n:"):
        nid = fact_id[2:]
        text = str(value or "").strip()
        st.notes = [({**n, "text": text[:300]} if n["id"] == nid else n) for n in st.notes if n["id"] != nid or text]
    else:
        raise ValueError(f"not editable: {fact_id}")
    if fact_id.startswith("h:"):
        st.ds.client.extra["household_edited"] = True
    st.version += 1
    st.ai_facts.clear()
    return overrides


CHAT_SYSTEM = """You help a bank client check the facts and assumptions behind their financial plan. You get the current
list (id, label, value, unit, editable) and the client's message. Output JSON only:
{{"reply": "1-3 plain sentences", "changes": [{{"id": "a:... or h:...", "value": number}}], "notes": ["a life fact in the client's words"]}}
Change only editable items the message is about, and only with numbers the client gave (never invent numbers). Values use
the item's unit: a share is 0.03 for 3%, CHF amounts are plain numbers. Anything that matters for their plans but has no
item (plans, family news, health, a move) becomes a short note. Write the reply in {language}."""

READ_SYSTEM = """You read a bank client's financial profile and tell them, in plain words, what the data says about their
life and what you are assuming. Output JSON only:
{{"summary": "two short sentences on where they stand", "observations": [{{"text": "one short sentence", "basis": "what in the data shows it"}}]}}
At most 5 observations about their life (pets, commuting, children, hobbies, travel, housing), each backed by the data.
Only use numbers that appear in the input. Write in {language}."""


def chat(svc: "PlanningService", client_id: str, message: str, overrides: dict | None, lang: str = "en") -> dict[str, Any]:
    facts = build(svc, client_id, overrides, lang)
    items = [{k: f[k] for k in ("id", "label", "value", "unit", "editable")} for g in ("money", "life", "future", "notes")
             for f in facts[g]]
    llm = get_llm(svc.cfg)
    reply, changes, notes = None, [], []
    if llm is not None:
        try:
            out = _json(llm.complete(CHAT_SYSTEM.format(language="German" if lang == "de" else "English"),
                                     json.dumps({"items": items, "message": message}, ensure_ascii=False, default=str), 1200))
            reply, changes, notes = out.get("reply"), out.get("changes") or [], out.get("notes") or []
        except Exception as exc:
            log.warning("facts chat failed: %s", exc)
    if reply is None:                                    # no LLM: keep what they said as a note
        reply = "Noted. You can also edit any line directly." if lang != "de" else "Notiert. Sie können jede Zeile auch direkt ändern."
        notes = [message]
    editable = {i["id"] for i in items if i["editable"]}
    applied = []
    for ch in changes:
        fid = str(ch.get("id", ""))
        if fid in editable and not fid.startswith("n:"):
            try:
                overrides = apply(svc, client_id, fid, ch.get("value"), overrides)
                applied.append(fid)
            except (ValueError, TypeError):
                continue
    for n in notes[:3]:
        overrides = apply(svc, client_id, "n:new", n, overrides)
    return {"reply": reply, "changed": applied, "overrides": overrides, "facts": build(svc, client_id, overrides, lang)}


def read(svc: "PlanningService", client_id: str, lang: str = "en") -> dict[str, Any]:
    """The LLM's plain-words reading of the data (cached per language until something changes)."""
    st = svc.state(client_id)
    with st.lock:
        return _read(svc, client_id, st, lang)


def _read(svc: "PlanningService", client_id: str, st, lang: str) -> dict[str, Any]:
    if lang in st.ai_facts:
        return st.ai_facts[lang]
    llm = get_llm(svc.cfg)
    if llm is None:
        return {"summary": None, "observations": [], "available": False}
    p = st.profile
    data = {**situation(svc, client_id),
            "spending": [{"category": f.label, "monthly": round(f.monthly), "top_merchants": [m.merchant for m in f.top_merchants[:3]]}
                         for f in p.flows if f.kind == "spending"][:10],
            "regular_payments": [{"to": r.merchant, "every": r.period_label, "amount": round(-r.amount)} for r in p.recurring
                                 if r.active and r.amount < 0][:8],
            "detected": [h.label for h in p.hints]}
    try:
        out = _json(llm.complete(READ_SYSTEM.format(language="German" if lang == "de" else "English"),
                                 json.dumps(data, ensure_ascii=False, default=str), 1200))
        res = {"summary": out.get("summary"), "observations": out.get("observations", [])[:5], "available": True}
    except Exception as exc:
        log.warning("facts reading failed: %s", exc)
        res = {"summary": None, "observations": [], "available": False}
    st.ai_facts[lang] = res
    return res
