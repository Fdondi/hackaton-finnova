from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from ..llm import get_llm
from .llm_agent import LLMAgent
from .rules_agent import RulesAgent
from .session import Session, WhatIfResult, WhatIfStep
from .tools import vocabulary

if TYPE_CHECKING:
    from ..service import PlanningService

log = logging.getLogger("mygoal.agent")


class WhatIfEngine:
    """Routes a what-if: existing specialist lever -> LLM agent -> rules agent. Sessions live in memory."""

    def __init__(self, svc: "PlanningService"):
        self.svc = svc
        self.sessions: dict[str, Session] = {}

    def start(self, client_id: str, goal_id: str, text: str, lang: str = "en", allow_llm: bool = True) -> WhatIfResult:
        s = Session(client_id=client_id, goal_id=goal_id, text=text, lang=lang)
        self.sessions[s.id] = s
        hit = self._specialist(s)
        if hit:
            return hit
        llm = get_llm(self.svc.cfg) if allow_llm else None
        if llm is not None:
            result = LLMAgent(self.svc, llm).start(s)
            if result.status != "error":
                return result
            log.warning("LLM agent failed (%s %s), falling back to rules: %s", llm.name, llm.model, result.message)
            s.steps.append(WhatIfStep(kind="note", name="fallback", summary=f"LLM unavailable ({result.message[:80]}), using rules"))
        return RulesAgent(self.svc).start(s)

    def answer(self, session_id: str, answer: str) -> WhatIfResult:
        s = self.sessions[session_id]
        if s.agent == "llm":
            llm = get_llm(self.svc.cfg)
            return LLMAgent(self.svc, llm).answer(s, answer)
        return RulesAgent(self.svc).answer(s, answer)

    def _specialist(self, s: Session) -> WhatIfResult | None:
        low = f" {s.text.lower()} "
        goal = self.svc.goal(s.client_id, s.goal_id)
        base = self.svc.planner(s.client_id, goal, {}).base
        available = {lv.lever_id: lv for lv in self.svc.levers(s.client_id, goal, base, {})}
        for lever_id, words in vocabulary()["specialists"].items():
            if lever_id in available and any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
                lv = available[lever_id]
                s.agent = "specialist"
                ev = self.svc.evaluate_lever(s.client_id, s.goal_id, lever_id)
                return WhatIfResult(session_id=s.id, status="existing_lever", agent="specialist", lever_id=lever_id,
                                    message=lv.title + (f": {lv.description}" if lv.description else ""), evaluation=ev,
                                    steps=[WhatIfStep(kind="note", name="specialist", summary=f"matched specialist lever '{lever_id}'")])
        return None
