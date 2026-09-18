"""Tool-use agent. The loop pauses on ask_user and resumes when the client answers (next HTTP request)."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..llm import LLMClient, ToolCall
from .session import Session, WhatIfQuestion, WhatIfResult, WhatIfStep
from .tools import life_event_evidence, profile_summary, propose_lever, search_transactions, tool_specs

if TYPE_CHECKING:
    from ..service import PlanningService

SYSTEM = """You help a bank client explore a "what if" for their financial plan. A simulation engine computes outcomes; \
your job is to turn the client's idea into one lever built from primitives, with every number stated as a labelled estimate.

- Ground estimates in the client's data first: get_profile_summary, search_transactions.
- For life events (baby, wedding, separation, new job, moving, inheritance) call life_event_evidence and build on what \
happened to real people in the bank's data (source "population"); say how many people the numbers come from.
- Ask the client only for facts you can't reasonably estimate (e.g. what something could sell for), at most {max_questions} questions.
- Build the lever with propose_lever. Combine primitives when needed (selling a hobby = asset_dispose for the sale + \
recurring_change for spending that stops). Amounts from bookings use source "transactions", the client's answers "user", \
your own guesses "llm_estimate" with low and high.
- If the idea can't be modelled with the primitives, say what's missing instead of guessing.
- End with one or two plain sentences for the client in {language}: CHF per month, no jargon, never "you should".
You can make at most {max_steps} tool calls."""


def _summary(call: ToolCall, result: str) -> str:
    if call.name == "search_transactions":
        try:
            r = json.loads(result)
            return f"searched '{call.input.get('query')}': {len(r['matches'])} merchants, CHF {r['monthly_last_12m']:.0f}/month"
        except (ValueError, KeyError):
            pass
    if call.name == "propose_lever":
        return f"built lever '{call.input.get('title')}'"
    if call.name == "life_event_evidence":
        try:
            r = json.loads(result)
            return f"bank data on '{r['event']}': " + (f"{r['people']} people" if r.get("available") else "none")
        except (ValueError, KeyError):
            pass
    return call.name.replace("_", " ")


class LLMAgent:
    def __init__(self, svc: "PlanningService", llm: LLMClient):
        self.svc, self.llm = svc, llm
        llm_cfg = svc.cfg["app"]["llm"]
        self.max_steps, self.max_questions = llm_cfg["max_agent_steps"], llm_cfg["max_questions"]

    def start(self, s: Session) -> WhatIfResult:
        s.agent = "llm"
        system = SYSTEM.format(max_questions=self.max_questions, max_steps=self.max_steps,
                               language="German" if s.lang == "de" else "English")
        conv = self.llm.conversation(system, tool_specs(self.max_questions))
        conv.add_user(s.text)
        s.state["conv"] = conv
        return self._run(s)

    def answer(self, s: Session, answer: str) -> WhatIfResult:
        conv = s.state["conv"]
        pending: ToolCall = s.state.pop("pending")
        deferred = s.state.pop("deferred", [])
        s.steps.append(WhatIfStep(kind="note", name="answer", summary=str(answer)))
        conv.add_tool_results(deferred + [(pending.id, json.dumps({"answer": answer}), False)])
        return self._run(s)

    def _execute(self, s: Session, call: ToolCall) -> tuple[str, bool]:
        try:
            if call.name == "get_profile_summary":
                return json.dumps(profile_summary(self.svc, s.client_id, s.goal_id), default=str), False
            if call.name == "search_transactions":
                return json.dumps(search_transactions(self.svc, s.client_id, str(call.input.get("query", ""))), default=str), False
            if call.name == "propose_lever":
                return propose_lever(self.svc, s, call.input, created_by="llm")
            if call.name == "life_event_evidence":
                return json.dumps(life_event_evidence(self.svc, str(call.input.get("event", ""))), default=str), False
            return f"Unknown tool {call.name}", True
        except Exception as exc:
            return f"Tool failed: {exc}", True

    def _run(self, s: Session) -> WhatIfResult:
        conv = s.state["conv"]
        for _ in range(self.max_steps + 3):
            turn = conv.step()
            if turn.stop_reason in ("error", "refusal"):
                return self._finish(s, "error" if not s.lever_id else "lever", turn.text or "The assistant couldn't handle this.")
            if not turn.tool_calls:
                return self._finish(s, "lever" if s.lever_id else "unsupported", turn.text)
            results, question_call = [], None
            for call in turn.tool_calls:
                s.tool_calls += 1
                if call.name == "ask_user":
                    if question_call is None and s.questions < self.max_questions:
                        question_call = call
                    else:
                        results.append((call.id, "No more questions: use a labelled llm_estimate with low/high instead.", True))
                    continue
                if s.tool_calls > self.max_steps:
                    results.append((call.id, "Tool budget used up: answer the client now.", True))
                    continue
                content, err = self._execute(s, call)
                s.steps.append(WhatIfStep(name=call.name, summary=("rejected: " + content[:120]) if err else _summary(call, content)))
                results.append((call.id, content, err))
            if question_call is not None:
                s.questions += 1
                s.state["pending"], s.state["deferred"] = question_call, results
                q = question_call.input
                question = WhatIfQuestion(id=question_call.id, text=str(q.get("question", "")), kind=q.get("kind", "number"),
                                          unit=q.get("unit"), options=q.get("options") or [], min=q.get("min"), max=q.get("max"),
                                          default=q.get("default"))
                s.steps.append(WhatIfStep(name="ask_user", summary=question.text))
                return WhatIfResult(session_id=s.id, status="question", agent="llm", question=question, steps=s.steps,
                                    lever_id=s.lever_id)
            conv.add_tool_results(results)
        return self._finish(s, "lever" if s.lever_id else "unsupported", "")

    def _finish(self, s: Session, status: str, message: str) -> WhatIfResult:
        return WhatIfResult(session_id=s.id, status=status, agent="llm", message=message.strip(), lever_id=s.lever_id,
                            steps=s.steps, evaluation=s.state.get("evaluation"))
