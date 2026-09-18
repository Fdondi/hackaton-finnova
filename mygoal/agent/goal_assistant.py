"""Goals page: suggest goals from the client's situation, and turn one sentence into a goal (one question allowed).

The LLM proposes and phrases. Amounts it has to make up are rough typical Swiss prices, shown as editable estimates;
the engine still does every calculation. Without an LLM, rules on the data and a small parser keep the page working.
Every goal is validated by its goal plugin before it reaches the client.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import TYPE_CHECKING, Any

from ..goals import GOALS, parse_params
from ..llm import get_llm
from ..model import GoalSpec, add_months, month_start

if TYPE_CHECKING:
    from ..service import PlanningService

log = logging.getLogger("mygoal.agent")

GOAL_TYPES = {"home": "buying a home (amount = property price)", "target": "any purchase or saving target (amount = total cost)",
              "retirement": "retiring at an age (retirement_age)"}
CATEGORIES = ["home", "car", "travel", "education", "hobby", "collection", "business", "family", "safety", "health",
              "retirement", "other"]
_CATEGORY_HINTS = (("car", "car"), ("auto", "car"), ("house", "home"), ("home", "home"), ("wohnung", "home"),
                   ("trip", "travel"), ("travel", "travel"), ("reise", "travel"), ("study", "education"),
                   ("education", "education"), ("school", "education"), ("hobby", "hobby"), ("funko", "collection"),
                   ("collection", "collection"), ("farm", "business"), ("business", "business"),
                   ("cushion", "safety"), ("emergency", "safety"), ("health", "health"), ("retire", "retirement"))

SUGGEST_SYSTEM = """You suggest financial life goals for one bank client, based on their situation. Output JSON only:
{{"goals": [{{"type": "home|target|retirement", "category": "{categories}", "label": "max 40 chars", "amount": CHF,
"years": years from today, "kind": "spend|save", "retirement_age": only for retirement,
"reason": "one short sentence that refers to their situation"}}]}}
kind (target goals): "spend" if the money is paid out at the date, "save" if it just has to be set aside.
Suggest {n} goals this particular person might really dream of. Be creative and specific, not generic: read their age,
family, work, interests and the shops they pay (a Games Workshop customer might want a big Warhammer army, a hiker a
Himalaya trek, a student a semester abroad, a collector the complete Funko Pop series, a farmer's kid their own quail
farm). At most one practical goal; the others should be personal and surprising. Every goal needs a different
category, and none of these categories are allowed because the client already has them: {taken}.
Don't repeat these existing or rejected goals: {existing}. Never suggest retirement if one exists.
Amounts are rough typical Swiss prices (shown as editable estimates). Write label and reason in {language}.
Goal types: {types}."""

DRAFT_SYSTEM = """You turn a bank client's sentence into exactly one financial goal. Output JSON only, one of:
{{"goal": {{"type": "home|target|retirement", "label": "max 40 chars", "amount": CHF, "years": years from today,
"kind": "spend (paid out at the date) or save (has to be set aside, e.g. an emergency fund)",
"retirement_age": only for retirement, "reason": "one sentence: what you understood and what you estimated"}}}}
{{"question": "one short question"}}
Ask a question only if something essential is missing that you cannot reasonably estimate; {question_rule}
If the client gives no amount, estimate a typical Swiss price and say so in the reason. Today is {today}.
Write label, reason and question in {language}. Goal types: {types}."""


def _json(text: str) -> dict:
    """The first JSON object in an LLM reply (tolerates code fences and chatter)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


def _slug(label: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:24] or "goal"
    slug, i = base, 2
    while slug in taken:
        slug, i = f"{base}_{i}", i + 1
    return slug


def situation(svc: "PlanningService", client_id: str) -> dict[str, Any]:
    """What the LLM may know about the client: compact, rounded, no raw bookings."""
    st = svc.state(client_id)
    p, c = st.profile, st.ds.client
    x = c.extra
    kids = [p.as_of.year - y for y in c.household.children_birth_years]
    return {
        "today": p.as_of.isoformat(), "age": p.age, "sex": x.get("sex"), "canton": c.canton, "city": x.get("city"),
        "occupation": x.get("occupation"), "employment": x.get("employment_type"), "married": c.household.adults >= 2,
        "children_ages": kids, "interests": x.get("interests", []),
        "net_income_monthly": round(p.income.salary_net_monthly_avg + p.income.other_income_monthly),
        "spending_monthly": round(p.spending_monthly), "free_cash_monthly": round(p.free_cash_flow_monthly),
        "cash": round(p.balances.liquid), "invested": round(p.balances.invested), "pillar3a": round(p.balances.p3a),
        "owns_home": bool(x.get("owns_property")), "rent_monthly": round(p.monthly("housing")) if x.get("renter") else None,
        "has_car": p.hint("car") is not None, "top_spending": [f.label for f in p.flows if f.kind == "spending"][:5],
        "shops_and_hobbies": sorted({m.merchant for f in p.flows if f.category in ("leisure_hobby", "shopping", "travel", "education")
                                     for m in f.top_merchants[:4]})[:12],
        "notes_from_client": [n["text"] for n in st.notes],
    }


def to_goal(d: dict, as_of: date, canton: str | None, taken: set[str], origin: str, status: str = "suggested") -> GoalSpec | None:
    """Validate one LLM/rule goal dict into a GoalSpec (None if it doesn't make sense)."""
    typ = d.get("type")
    if typ not in GOAL_TYPES:
        return None
    label = str(d.get("label") or "").strip()[:60] or {"home": "Own home", "retirement": "Retirement"}.get(typ, "My goal")
    start = month_start(as_of)
    if typ == "retirement":
        age = int(float(d.get("retirement_age") or 65))
        params, when = {"retirement_age": max(50, min(age, 70))}, None
    else:
        amount = float(d.get("amount") or 0)
        if amount <= 0:
            return None
        years = float(d.get("years") or (5 if typ == "home" else 2))
        when = date(start.year + max(0, round(years)), 6, 1)          # goal dates are June 1 of a year
        when = when if when > start else date(start.year + 1, 6, 1)
        kind = "save" if str(d.get("kind", "")).lower().startswith("save") else "spend"
        params = {"price": round(amount, -3), "canton": canton} if typ == "home" else {"amount": round(amount, -1), "kind": kind}
    category = _category(d, typ)
    goal = GoalSpec(id=_slug(label, taken), type=typ, label=label, target_date=when, params=params, status=status, origin=origin,
                    note=(str(d.get("reason") or "").strip()[:200] or None), category=category)
    parse_params(GOALS.get(typ), goal)          # raises if the plugin disagrees
    return goal


# ---------------------------------------------------------------------------------------------------- suggestions
def _category(d: dict, typ: str) -> str:
    """LLM category if valid, else guess from the label so two 'car' ideas still collide."""
    raw = str(d.get("category") or "").lower()
    if raw in CATEGORIES:
        return raw
    if typ in ("home", "retirement"):
        return typ
    blob = f"{d.get('label', '')} {d.get('reason', '')}".lower()
    for word, cat in _CATEGORY_HINTS:
        if word in blob:
            return cat
    return "other"


def rule_suggestions(svc: "PlanningService", client_id: str) -> list[dict]:
    """Personal suggestions that need no LLM (on top of the adapter's data-based seeds)."""
    s = situation(svc, client_id)
    existing = svc.state(client_id).goals
    taken_cat = {g.category for g in existing if g.category}
    age, out = s["age"] or 40, []
    if age < 18 and "hobby" not in taken_cat:
        out.append({"type": "target", "label": "A new games console", "amount": 600, "years": 0.5, "category": "hobby",
                    "reason": "Saved from pocket money in about half a year"})
    has_retirement = any(g.type == "retirement" for g in existing)
    if age >= 50 and s["employment"] in ("employed", "self_employed") and not has_retirement:
        out.append({"type": "retirement", "label": "Retire early at 60", "retirement_age": 60,
                    "reason": f"At {age}, early retirement is the big question"})
    if s["children_ages"] and "education" not in taken_cat:
        out.append({"type": "target", "label": "Education fund for the kids", "amount": 15_000 * len(s["children_ages"]), "kind": "save",
                    "category": "education",
                    "years": max(1, 18 - min(s["children_ages"])), "reason": "Ready when your children start their education"})
    if s["has_car"] and s["cash"] + s["invested"] > 250_000 and "car" not in taken_cat:
        out.append({"type": "target", "label": "A sports car", "amount": 180_000, "years": 2, "category": "car",
                    "reason": "You drive, and you have the savings for a dream car"})
    if s["spending_monthly"] and s["cash"] < 3 * s["spending_monthly"] and age >= 18 and "safety" not in taken_cat:
        out.append({"type": "target", "label": "Safety cushion of 3 months", "amount": 3 * s["spending_monthly"], "years": 1, "kind": "save",
                    "category": "safety",
                    "reason": "Your cash covers less than three months of spending"})
    return out


def suggest(svc: "PlanningService", client_id: str, lang: str = "en", use_llm: bool = True, more: bool = False) -> list[GoalSpec]:
    """Add suggestions to the client's goal list (rules always, the LLM once per client). Returns the full list."""
    st = svc.state(client_id)
    with st.lock:           # a second call waits for the first one's LLM ideas instead of returning without them
        goals = _suggest(svc, client_id, st, lang, use_llm, more)
        if use_llm:
            _translate_ai_goals(svc, st, lang)
        return goals


def _translate_ai_goals(svc: "PlanningService", st, lang: str) -> None:
    """AI suggestions were written in the language of the moment: translate them once when the client switches."""
    todo = [g for g in st.goals if g.origin == "ai" and lang not in g.i18n]
    llm = get_llm(svc.cfg) if todo else None
    if llm is None:
        return
    items = [{"id": g.id, "label": g.label, "note": g.note or ""} for g in todo]
    try:
        out = _json(llm.complete(f"Translate these goal labels and notes into {'German' if lang == 'de' else 'English'} "
                                 "(Swiss usage, keep them short). Output JSON only: {\"items\": [{\"id\", \"label\", \"note\"}]}",
                                 json.dumps({"items": items}, ensure_ascii=False), 1500)).get("items", [])
    except Exception as exc:
        log.warning("goal translation failed: %s", exc)
        return
    by_id = {str(x.get("id")): x for x in out}
    with st.goals_lock:
        for g in st.goals:
            if g.id in by_id:
                g.i18n[lang] = {"label": str(by_id[g.id].get("label") or g.label)[:60], "note": str(by_id[g.id].get("note") or "")[:200]}


_GENERIC = {"fund", "your", "with", "from", "goal", "save", "saving", "savings", "plan", "family", "für", "eine", "einen",
            "own", "new", "neue", "neuen", "kids", "children", "the", "for", "and", "buy", "get", "und", "ein", "der", "die",
            "das", "mit", "big", "dream", "trip", "fund"}


def _same_idea(a: GoalSpec, b: GoalSpec) -> bool:
    """Near-duplicates: one home and one retirement are enough; otherwise the same category (except "other") or a
    shared meaningful word ("Family car" vs "Buy a car")."""
    if a.type != b.type:
        return False
    if a.type in ("home", "retirement"):
        return True
    if a.category and a.category == b.category and a.category != "other":
        return True
    words = lambda g: {w for w in re.findall(r"[a-zäöüéè]+", g.label.lower()) if len(w) >= 3 and w not in _GENERIC}  # noqa: E731
    return bool(words(a) & words(b))


def _suggest(svc: "PlanningService", client_id: str, st, lang: str, use_llm: bool, more: bool = False) -> list[GoalSpec]:
    as_of, canton = st.profile.as_of, st.ds.client.canton
    def key(g: dict | GoalSpec) -> tuple:
        get = g.get if isinstance(g, dict) else lambda k, default=None: getattr(g, k, None) or g.params.get(k, default)
        if get("type") == "retirement":
            try:
                return ("retirement", int(float(get("retirement_age", 65) or 65)))
            except (TypeError, ValueError):
                return ("retirement", 65)
        return (get("type"), str(get("label") or "").lower())

    known = {key(g) for g in st.goals}
    ideas: list[tuple[dict, str]] = [(d, "data") for d in rule_suggestions(svc, client_id)]
    llm = get_llm(svc.cfg) if use_llm and (more or not st.ai_suggested) else None
    cap = 6 + (4 if more else 0) + sum(1 for g in st.goals if g.status == "suggested") * (1 if more else 0)
    if llm is not None:
        st.ai_suggested = True
        existing = ", ".join([g.label for g in st.goals] + [label for _, label in st.dismissed]) or "none"
        taken = sorted({g.category for g in st.goals if g.category and g.category != "other"}
                       | ({"home"} if any(g.type == "home" for g in st.goals) else set())
                       | ({"retirement"} if any(g.type == "retirement" for g in st.goals) else set())) or ["none"]
        system = SUGGEST_SYSTEM.format(n=4, existing=existing, taken=", ".join(taken), categories="|".join(CATEGORIES),
                                       language="German" if lang == "de" else "English", types=json.dumps(GOAL_TYPES))
        try:
            ideas += [(d, "ai") for d in _json(llm.complete(system, json.dumps(situation(svc, client_id)), 1500)).get("goals", [])]
        except Exception as exc:  # the page still works with the rules' ideas
            log.warning("goal suggestions failed: %s", exc)
    for d, origin in ideas:
        if key(d) in known or (d.get("type"), str(d.get("label") or "").lower()) in st.dismissed \
                or len([g for g in st.goals if g.status == "suggested"]) >= cap:
            continue
        try:
            g = to_goal(d, as_of, canton, {x.id for x in st.goals}, origin)
        except Exception:
            g = None
        if g is not None:
            if origin == "ai":
                g.i18n[lang] = {"label": g.label, "note": g.note or ""}
            with st.goals_lock:                    # the client may be deleting or confirming meanwhile
                if not any(_same_idea(x, g) for x in st.goals):
                    st.goals = [*st.goals, g]
                    known.add(key(g))
    st.version += 1
    return list(st.goals)


# ---------------------------------------------------------------------------------------------------- one sentence -> goal
_AMOUNT = re.compile(r"(?:chf|fr\.?)?\s*(\d[\d'’.,]*)\s*(k|tausend|thousand|mio|million)?\s*(?:chf|fr\.?|franken)?", re.I)
_YEARS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(years?|jahren?|j\b|months?|monaten?)", re.I)
_YEAR = re.compile(r"\b(20[2-6]\d)\b")
_AGE = re.compile(r"\b(?:at|mit)\s*(\d{2})\b", re.I)


def _parse_rules(text: str, as_of: date) -> dict:
    low = text.lower()
    typ = "retirement" if re.search(r"retir|pension|rente|frühpens", low) else \
        "home" if re.search(r"\b(house|home|flat|apartment|wohnung|haus|eigenheim)\b", low) else "target"
    label = re.sub(r"^(i (want|would like|'d like|wish) to|i want|ich (möchte|will|würde gerne)|wir (möchten|wollen))\s+", "",
                   text.strip().rstrip(".!"), flags=re.I)
    d: dict[str, Any] = {"type": typ, "label": (label[:1].upper() + label[1:])[:40]}
    if re.search(r"\b(save|saved|savings|fund|reserve|cushion|sparen|gespart|notgroschen|polster|rücklage|reserve)\b", low):
        d["kind"] = "save"
    if typ == "retirement":
        m = _AGE.search(low)
        d["retirement_age"] = int(m.group(1)) if m else 60
        return d
    if m := _YEARS.search(low):
        n = float(m.group(1).replace(",", "."))
        d["years"] = n / 12 if m.group(2).lower().startswith(("month", "monat")) else n
    elif m := _YEAR.search(low):
        d["years"] = max(1, int(m.group(1)) - as_of.year)
    rest = _YEARS.sub(" ", _YEAR.sub(" ", low))          # numbers left over are amounts
    for m in _AMOUNT.finditer(rest):
        raw = m.group(1).replace("'", "").replace("’", "").replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        mult = {"k": 1e3, "tausend": 1e3, "thousand": 1e3, "mio": 1e6, "million": 1e6}.get((m.group(2) or "").lower(), 1)
        if v * mult >= 100:
            d["amount"] = v * mult
            break
    return d


def draft(svc: "PlanningService", client_id: str, text: str, lang: str = "en", question: str | None = None,
          answer: str | None = None) -> dict[str, Any]:
    """{"status": "question", "question": ...} or {"status": "goal", "goal": GoalSpec} (added as a suggestion)."""
    st = svc.state(client_id)
    as_of, canton = st.profile.as_of, st.ds.client.canton
    llm = get_llm(svc.cfg)
    d: dict | None = None
    if llm is not None:
        system = DRAFT_SYSTEM.format(today=as_of.isoformat(), language="German" if lang == "de" else "English",
                                     types=json.dumps(GOAL_TYPES),
                                     question_rule="you already asked one, so return a goal now." if answer is not None
                                     else "at most one question.")
        prompt = json.dumps({"client_sentence": text, "your_question": question, "client_answer": answer,
                             "client_situation": situation(svc, client_id)}, ensure_ascii=False)
        try:
            out = _json(llm.complete(system, prompt, 1200))
            if out.get("question") and answer is None:
                return {"status": "question", "question": str(out["question"])[:200]}
            d = out.get("goal")
        except Exception as exc:
            log.warning("goal draft failed: %s", exc)
    if d is None:                                    # rules: parse what we can, ask once for a missing amount
        d = _parse_rules(text + (" " + answer if answer else ""), as_of)
        d["label"] = _parse_rules(text, as_of)["label"]
        if d["type"] != "retirement" and "amount" not in d:
            if answer is None:
                return {"status": "question", "question": "How much will it cost, roughly (CHF)?" if lang != "de"
                        else "Wie viel wird es ungefähr kosten (CHF)?"}
            return {"status": "error", "message": "Sorry, I couldn't read an amount. Try e.g. 'a car for CHF 30'000 in 2 years'."}
        d["reason"] = "Read from your sentence" if lang != "de" else "Aus Ihrem Satz gelesen"
    goal = to_goal(d, as_of, canton, {g.id for g in st.goals}, "user", status="confirmed")   # they asked for it
    if goal is None:
        return {"status": "error", "message": "Sorry, I couldn't turn that into a goal."}
    same = next((g for g in st.goals if g.type == goal.type and g.label.lower() == goal.label.lower()
                 and g.target_date == goal.target_date and g.params == goal.params), None)
    if same is not None:                                  # typed twice: keep one
        return {"status": "goal", "goal": same}
    if goal.type == "retirement":                          # only one retirement goal: the new one replaces it
        with st.goals_lock:
            st.goals = [g for g in st.goals if g.type != "retirement"]
    with st.goals_lock:
        st.goals = [*st.goals, goal]
        st.version += 1
    return {"status": "goal", "goal": goal}



# ---------------------------------------------------------------------------------------------------- ad-hoc ideas
IDEAS_SYSTEM = """You propose ad-hoc actions that could help one bank client reach a financial goal they are likely to
miss. Output JSON only:
{{"ideas": [{{"title": "short action", "description": "one plain sentence", "group": "no_lifestyle_cost|structural|behavioural",
"effort": "low|medium|high", "parts": [{{"primitive": "name", "params": {{...}}}}]}}]}}
Propose {n} ideas that fit THIS client (their spending, merchants, assets, interests), concrete and realistic, and
different from the standard options they already see: {standard}. Ideas must create money for the goal: spend less on
something specific, earn more, sell something, avoid a cost. Don't move money between the client's own accounts
(no reallocate), don't change the goal itself. Build each idea from the primitives below. Every amount
is an Estimate: use source "transactions" only for amounts taken from the client's data, otherwise "llm_estimate" with
low and high. Write title and description in {language}.
Primitives:
{catalogue}"""


def ideas(svc: "PlanningService", client_id: str, goal_id: str, lang: str = "en", n: int = 3, more: bool = False) -> dict[str, Any]:
    """The AI's own ideas for one goal, registered as levers (the engine computes their effect). Cached per goal;
    `more` asks again for new ones and adds them."""
    from .session import Session
    from .tools import primitive_catalogue, propose_lever
    st = svc.state(client_id)
    with st.lock:
        before = st.ai_ideas.get(goal_id, [])
        if goal_id in st.ai_ideas and not more:
            return {"ids": before, "cached": True}
        llm = get_llm(svc.cfg)
        if llm is None:
            return {"ids": [], "available": False}
        goal = svc.goal(client_id, goal_id)
        p = st.profile
        pl = svc.planner(client_id, goal, {})
        standard = [lv.title for lv in svc.levers(client_id, goal, pl.base, {}) if lv.group != "life_event"]
        standard += [st.custom_levers[i].title for i in before if i in st.custom_levers]
        data = {"client": situation(svc, client_id), "goal": goal.model_dump(mode="json"),
                "spending": [{"category": f.label, "monthly": round(f.monthly), "top_merchants": [m.merchant for m in f.top_merchants[:3]]}
                             for f in p.flows if f.kind == "spending"][:10],
                "detected": [h.label for h in p.hints]}
        system = IDEAS_SYSTEM.format(n=n, standard="; ".join(standard) or "none", catalogue=primitive_catalogue(),
                                     language="German" if lang == "de" else "English")
        prompt = json.dumps(data, ensure_ascii=False, default=str)
        ids: list[str] = []
        rejected: list[tuple[dict, str]] = []

        def register(proposals: list[dict]) -> None:
            for idea in proposals:
                if len(ids) >= n:
                    return
                for part in idea.get("parts") or []:     # tolerate fields next to "primitive" instead of in "params"
                    if not part.get("params"):
                        part["params"] = {k: v for k, v in part.items() if k not in ("primitive", "params")}
                s = Session(client_id=client_id, goal_id=goal_id, text=str(idea.get("title", "")), lang=lang)
                msg, err = propose_lever(svc, s, idea, created_by="llm")
                if err or not s.lever_id:
                    rejected.append((idea, msg[:300]))
                else:
                    ids.append(s.lever_id)

        try:
            register(_json(llm.complete(system, prompt, 3000)).get("ideas", []))
            if rejected and len(ids) < n:                 # one repair round with the validation errors
                fix = [{"idea": i, "error": e} for i, e in rejected]
                rejected.clear()
                register(_json(llm.complete(system, prompt + "\n\nThese ideas were rejected; return them fixed (same JSON "
                                            "format, only valid primitives and fields):\n" + json.dumps(fix, ensure_ascii=False),
                                            3000)).get("ideas", []))
        except Exception as exc:
            log.warning("goal ideas failed: %s", exc)
        if rejected:
            log.warning("goal ideas rejected: %s", [e for _, e in rejected])
        for i in list(ids):                               # keep only what the engine says actually helps
            ev = svc.evaluate_lever(client_id, goal_id, i)
            if (ev.get("months_gained") or 0) <= 0 and ev.get("delta_p", 0) <= 0.005:
                svc.remove_custom_lever(client_id, i)
                ids.remove(i)
        st.ai_ideas[goal_id] = [*before, *ids]
        return {"ids": ids, "rejected": len(rejected)}


# ---------------------------------------------------------------------------------------------------- suggest a value
VALUE_SYSTEM = """A bank client is answering a question while planning their finances. Propose a reasonable answer for
THIS client: think it through with typical Swiss prices, rents, wages, returns and costs, and their situation. Output
JSON only: {{"value": number (or a short text if the question isn't about a number), "low": number or null,
"high": number or null, "unit": "CHF, CHF/month, %, years, ...", "reason": "one or two sentences: what the number is based on"}}
Give a realistic middle value, not an optimistic one. Write the reason in {language}."""


def suggest_value(svc: "PlanningService", client_id: str, question: str, context: str = "", lang: str = "en") -> dict[str, Any]:
    """"Suggest a value" for a question the assistant asked: the AI's reasoned estimate, labelled as such."""
    llm = get_llm(svc.cfg)
    if llm is None:
        return {"available": False}
    try:
        out = _json(llm.complete(VALUE_SYSTEM.format(language="German" if lang == "de" else "English"),
                                 json.dumps({"question": question, "context": context, "client": situation(svc, client_id)},
                                            ensure_ascii=False, default=str), 800))
    except Exception as exc:
        log.warning("value suggestion failed: %s", exc)
        return {"available": False}
    return {"available": True, "value": out.get("value"), "low": out.get("low"), "high": out.get("high"),
            "unit": out.get("unit"), "reason": out.get("reason")}
