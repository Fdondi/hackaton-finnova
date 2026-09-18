"""LLM-free what-if agent: intent regexes + transaction search + at most two questions.

Handles "sell / stop / buy / side income / part-time / one-off" ideas well enough for a demo without any model,
and produces exactly the same lever shape as the LLM agent.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .session import Session, WhatIfQuestion, WhatIfResult, WhatIfStep
from .tools import expand_terms, propose_lever, search_transactions, vocabulary

if TYPE_CHECKING:
    from ..service import PlanningService

T = {
    "en": {
        "sale": "Roughly what could your {obj} sell for?",
        "spend": "How much do you spend on {obj} per month?",
        "price": "What would {obj} cost?",
        "running": "What would it cost to run per month (insurance, upkeep, fees)?",
        "extra": "How much extra would you earn per month, before tax?",
        "work_share": "What percentage would you work?",
        "amount": "How much is it, roughly?",
        "when": "In how many months?",
        "unsupported": "I couldn't turn this into numbers. Try phrasing it as selling, stopping, buying, earning, or a one-off amount.",
        "done": "{title}: about {monthly}/month for your plan.",
    },
    "de": {
        "sale": "Was könnte Ihr {obj} ungefähr einbringen?",
        "spend": "Wie viel geben Sie monatlich für {obj} aus?",
        "price": "Was würde {obj} kosten?",
        "running": "Was kostet es pro Monat im Unterhalt (Versicherung, Pflege, Gebühren)?",
        "extra": "Wie viel würden Sie pro Monat zusätzlich verdienen, vor Steuern?",
        "work_share": "Wie viel Prozent würden Sie arbeiten?",
        "amount": "Um welchen Betrag geht es ungefähr?",
        "when": "In wie vielen Monaten?",
        "unsupported": "Das konnte ich nicht in Zahlen fassen. Versuchen Sie: verkaufen, aufhören, kaufen, verdienen oder ein einmaliger Betrag.",
        "done": "{title}: etwa {monthly}/Monat für Ihren Plan.",
    },
}


def detect_intent(text: str) -> str | None:
    low = text.lower()
    for intent, pattern in vocabulary()["intents"].items():
        if re.search(pattern, low):
            return intent
    return None


def object_phrase(text: str, intent: str) -> str:
    """The thing the what-if is about: words after the verb (English) or before it (German verb-final)."""
    m = re.search(vocabulary()["intents"][intent], text.lower())
    stop = set(vocabulary()["stopwords"])

    def clean(chunk: str) -> list[str]:
        return [w for w in re.split(r"[^\wäöüÄÖÜéèà&-]+", chunk) if w and w.lower() not in stop and not w.isdigit()]

    after = clean(text[m.end():]) if m else []
    before = clean(text[: m.start()]) if m else clean(text)
    words = after or before[-3:]
    return " ".join(words[:4]) or "it"


TITLES = {
    "en": {"dispose": "Sell {obj}", "stop": "Stop {obj}", "reduce": "Spend less on {obj}", "acquire": "Buy {obj}",
           "side_income": "Side income: {obj}", "part_time": "Work {pct:.0f}%", "one_off": "One-off: {obj}"},
    "de": {"dispose": "{obj} verkaufen", "stop": "{obj} aufgeben", "reduce": "Weniger für {obj}", "acquire": "{obj} kaufen",
           "side_income": "Nebenerwerb: {obj}", "part_time": "{pct:.0f}% arbeiten", "one_off": "Einmalig: {obj}"},
}


class RulesAgent:
    def __init__(self, svc: "PlanningService"):
        self.svc = svc

    def start(self, s: Session) -> WhatIfResult:
        s.agent = "rules"
        intent = detect_intent(s.text)
        if intent is None:
            return WhatIfResult(session_id=s.id, status="unsupported", agent="rules", message=T[self._lang(s)]["unsupported"])
        obj = object_phrase(s.text, intent)
        found = search_transactions(self.svc, s.client_id, obj)
        s.state.update(intent=intent, obj=obj, found=found, answers={})
        s.steps.append(WhatIfStep(name="search_transactions",
                                  summary=f"'{obj}' ({', '.join(found['terms'][:4])}): {len(found['matches'])} merchants, "
                                          f"CHF {found['monthly_last_12m']:.0f}/month"))
        return self._next(s)

    def answer(self, s: Session, answer: str) -> WhatIfResult:
        if "asking" not in s.state:
            return WhatIfResult(session_id=s.id, status="unsupported", agent="rules", message=T[self._lang(s)]["unsupported"])
        key = s.state.pop("asking")
        try:
            s.state["answers"][key] = float(str(answer).replace("'", "").replace("CHF", "").replace("%", "").strip())
        except ValueError:
            s.state["answers"][key] = 0.0
        s.steps.append(WhatIfStep(kind="note", name="answer", summary=str(answer)))
        return self._next(s)

    @staticmethod
    def _lang(s: Session) -> str:
        return "de" if s.lang == "de" else "en"

    def _ask(self, s: Session, key: str, text: str, unit: str = "CHF", default: float | None = None) -> WhatIfResult:
        s.state["asking"] = key
        s.questions += 1
        q = WhatIfQuestion(id=key, text=text, kind="number", unit=unit, default=round(default) if default else None, min=0)
        s.steps.append(WhatIfStep(name="ask_user", summary=text))
        return WhatIfResult(session_id=s.id, status="question", agent="rules", question=q, steps=s.steps)

    def _next(self, s: Session) -> WhatIfResult:
        lang, st = self._lang(s), s.state
        intent, obj, found, ans = st["intent"], st["obj"], st["found"], st["answers"]
        monthly_seen = max(0.0, found["monthly_last_12m"])
        spent_total = max(0.0, -found["total"])
        tr = T[lang]
        pct_in_text = re.search(r"(\d{2,3}) ?(%|percent|prozent)", s.text.lower())
        if intent == "part_time" and pct_in_text and "work_share" not in ans:
            ans["work_share"] = float(pct_in_text.group(1))
        title = TITLES[lang][intent].format(obj=obj, pct=ans.get("work_share", 0))
        title = title[:1].upper() + title[1:]
        seen = {"value": round(monthly_seen, 2), "source": "transactions", "label": f"Spending on {obj} per month (last 12 months)",
                "unit": "CHF/month"}

        if intent == "dispose":
            if "sale" not in ans:
                return self._ask(s, "sale", tr["sale"].format(obj=obj), default=0.35 * spent_total if spent_total else None)
            if monthly_seen == 0 and "spend" not in ans:
                return self._ask(s, "spend", tr["spend"].format(obj=obj), unit="CHF/month")
            running = seen if monthly_seen else {"value": ans["spend"], "source": "user", "label": f"Spending on {obj} per month", "unit": "CHF/month"}
            parts = [{"primitive": "asset_dispose", "params": {
                "asset": obj, "months_to_sell": 2,
                "sale_value": {"value": ans["sale"], "low": 0.7 * ans["sale"], "high": 1.1 * ans["sale"], "source": "user",
                               "label": f"Sale value of {obj}"},
                "running_costs_monthly": running}}]
            return self._propose(s, title, parts, "structural", "medium")

        if intent in ("stop", "reduce"):
            share = 1.0 if intent == "stop" else 0.5
            if monthly_seen == 0 and "spend" not in ans:
                return self._ask(s, "spend", tr["spend"].format(obj=obj), unit="CHF/month")
            base = seen if monthly_seen else {"value": ans["spend"], "source": "user", "label": f"Spending on {obj} per month", "unit": "CHF/month"}
            delta = {**base, "value": round(base["value"] * share, 2), "label": ("Stop " if share == 1 else "Halve ") + base["label"].lower()}
            parts = [{"primitive": "recurring_change", "params": {"monthly_delta": delta, "behavioural": intent == "reduce"}}]
            return self._propose(s, title, parts, "behavioural", "low" if share == 1 else "medium")

        if intent == "acquire":
            if "price" not in ans:
                return self._ask(s, "price", tr["price"].format(obj=obj))
            if "running" not in ans:
                return self._ask(s, "running", tr["running"], unit="CHF/month")
            parts = [{"primitive": "asset_acquire", "params": {
                "asset": obj, "price": {"value": ans["price"], "source": "user", "label": f"Price of {obj}"},
                "running_costs_monthly": {"value": ans["running"], "low": 0.7 * ans["running"], "high": 1.4 * ans["running"],
                                          "source": "user", "label": f"Running costs of {obj}", "unit": "CHF/month"}}}]
            return self._propose(s, title, parts, "structural", "medium")

        if intent == "side_income":
            if "extra" not in ans:
                return self._ask(s, "extra", tr["extra"], unit="CHF/month")
            parts = [{"primitive": "income_change", "params": {
                "net_monthly_delta": {"value": ans["extra"], "low": 0.5 * ans["extra"], "high": 1.2 * ans["extra"], "source": "user",
                                      "label": "Extra income per month before tax", "unit": "CHF/month"},
                "volatility": 0.4, "taxable_side_income": True}}]
            return self._propose(s, title, parts, "structural", "high")

        if intent == "part_time":
            if "work_share" not in ans:
                return self._ask(s, "work_share", tr["work_share"], unit="%", default=80)
            factor = max(0.0, min(1.0, ans["work_share"] / 100))
            parts = [{"primitive": "income_change", "params": {
                "net_monthly_delta": {"value": 0, "source": "user", "label": "No other income change", "unit": "CHF/month"},
                "salary_factor": factor}}]
            return self._propose(s, title, parts, "structural", "high")

        if intent == "one_off":
            if "amount" not in ans:
                return self._ask(s, "amount", tr["amount"])
            if "when" not in ans:
                return self._ask(s, "when", tr["when"], unit="months", default=12)
            positive = bool(re.search(r"inherit|bonus|erb|windfall|gift|geschenk", s.text.lower()))
            amount = ans["amount"] if positive else -ans["amount"]
            parts = [{"primitive": "one_off", "params": {
                "amount": {"value": amount, "source": "user", "label": "Amount"}, "in_months": int(ans["when"])}}]
            return self._propose(s, title, parts, "life_event" if not positive else "structural", "medium")

        return WhatIfResult(session_id=s.id, status="unsupported", agent="rules", message=tr["unsupported"], steps=s.steps)

    def _propose(self, s: Session, title: str, parts: list[dict], group: str, effort: str) -> WhatIfResult:
        msg, err = propose_lever(self.svc, s, {"title": title, "parts": parts, "group": group, "effort": effort}, created_by="rules")
        if err:
            s.steps.append(WhatIfStep(name="propose_lever", summary=msg[:160]))
            return WhatIfResult(session_id=s.id, status="error", agent="rules", message=msg, steps=s.steps)
        ev = s.state.get("evaluation", {})
        s.steps.append(WhatIfStep(name="propose_lever", summary=f"built lever '{title}'"))
        from ..explain import chf
        return WhatIfResult(session_id=s.id, status="lever", agent="rules", lever_id=s.lever_id, steps=s.steps, evaluation=ev,
                            message=T[self._lang(s)]["done"].format(title=title, monthly=chf(ev.get("monthly_equivalent", 0))))


def mentioned_terms(text: str) -> list[str]:
    return expand_terms(text)
