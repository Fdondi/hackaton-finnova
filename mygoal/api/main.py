"""HTTP API. Thin: every endpoint is one call into PlanningService. OpenAPI docs at /docs.

    uv run uvicorn mygoal.api.main:app --reload --port 8080
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent import WhatIfResult
from ..config import ROOT
from ..levers import PRIMITIVES
from ..llm import llm_status
from ..model import GoalSpec
from ..partner_api import CONNECTORS, FORMAT, ImportResult, descriptor, partner, prompt, reply_schema, request
from ..service import CustomLever, PlanningService, PlanRequest, PlanResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("mygoal")

app = FastAPI(title="My Goal, My Plan", version="0.1.0",
              description="Financial stability layer: goals, gaps, levers and what-ifs from account data.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@lru_cache(maxsize=1)
def svc() -> PlanningService:
    return PlanningService()


@app.on_event("startup")
def _log_llm_status() -> None:
    status = llm_status(svc().cfg)
    if status["available"]:
        log.info("LLM: %s (%s)", status["provider"], status["model"])
    else:
        log.warning("LLM: unavailable (no ANTHROPIC_API_KEY, no OPENAI_API_KEY, no reachable OPENAI_BASE_URL) "
                    "-> what-ifs fall back to the rules agent")


def _client(client_id: str):
    try:
        return svc().state(client_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, f"unknown client {client_id}") from exc


class WhatIfRequest(BaseModel):
    text: str
    goal_id: str
    lang: str = "en"
    use_llm: bool = True


class AnswerRequest(BaseModel):
    answer: str


class LangRequest(BaseModel):
    lang: str = "en"
    use_llm: bool = True
    more: bool = False                            # "generate more suggestions": ask the AI again


class DraftRequest(BaseModel):
    text: str
    lang: str = "en"
    question: str | None = None
    answer: str | None = None


class TimelineRequest(BaseModel):
    active: list[str] = []                        # actions that are on (incl. "move:<goal>:<date>")
    focus: str | None = None                      # the goal whose actions the page shows (default: first failing)
    listed: list[str] = []                        # every action the page lists (cards and gains come back even if off)
    overrides: dict[str, dict[str, float]] = {}
    lang: str = "en"


class ValueRequest(BaseModel):
    question: str
    context: str = ""
    lang: str = "en"


class FactsRequest(BaseModel):
    overrides: dict[str, dict[str, float]] = {}
    lang: str = "en"


class FactEdit(FactsRequest):
    id: str
    value: float | str | None = None


class FactsChat(FactsRequest):
    message: str


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    s = svc()
    return {"llm": llm_status(s.cfg), "data_source": s.cfg.get_path("app.data.source"),
            "simulation": s.cfg["app"]["simulation"], "primitives": sorted(PRIMITIVES)}


@app.get("/api/i18n/{lang}")
def i18n(lang: str):
    return svc().i18n(lang)


@app.get("/api/clients")
def clients():
    return svc().list_clients()


@app.get("/api/clients/{client_id}/overview")
def overview(client_id: str, lang: str = "en"):
    _client(client_id)
    return svc().overview(client_id, lang)


@app.get("/api/clients/{client_id}/bookings")
def bookings(client_id: str, lang: str = "en"):
    _client(client_id)
    return svc().bookings(client_id, lang)


@app.post("/api/clients/{client_id}/plan", response_model=PlanResponse)
def plan(client_id: str, req: PlanRequest):
    _client(client_id)
    try:
        return svc().plan(client_id, req)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/clients/{client_id}/cross-goal")
def cross_goal(client_id: str, req: PlanRequest):
    _client(client_id)
    return svc().cross_goal_for(client_id, req)


@app.put("/api/clients/{client_id}/goals/{goal_id}")
def upsert_goal(client_id: str, goal_id: str, goal: GoalSpec):
    _client(client_id)
    if goal.id != goal_id:
        raise HTTPException(400, "goal id mismatch")
    try:
        return svc().upsert_goal(client_id, goal)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/api/clients/{client_id}/reset")
def reset_client(client_id: str):
    """Start this client over from the data: goals, dismissed suggestions, what-ifs, facts and integrations."""
    _client(client_id)
    svc().reset_client(client_id)
    return {"ok": True}


@app.get("/api/clients/{client_id}/goals")
def goals(client_id: str, lang: str = "en"):
    _client(client_id)
    return svc().localized_goals(client_id, lang)


@app.post("/api/clients/{client_id}/goals/suggest")
def suggest_goals(client_id: str, req: LangRequest):
    """Rules on the data plus (once per client) the LLM's ideas, added as suggested goals."""
    _client(client_id)
    from ..agent.goal_assistant import suggest
    suggest(svc(), client_id, req.lang, use_llm=req.use_llm, more=req.more)
    return svc().localized_goals(client_id, req.lang)


@app.post("/api/clients/{client_id}/goals/draft")
def draft_goal(client_id: str, req: DraftRequest):
    """One sentence -> a suggested goal, or one question first."""
    _client(client_id)
    from ..agent.goal_assistant import draft
    return draft(svc(), client_id, req.text, req.lang, req.question, req.answer)


@app.post("/api/clients/{client_id}/timeline")
def timeline(client_id: str, req: TimelineRequest):
    """All confirmed goals on one chart, each goal's chance, and a proposal for the ones at risk."""
    _client(client_id)
    from .. import timeline as tl
    return tl.build(svc(), client_id, req.active, req.overrides, req.lang, req.focus, req.listed)


@app.post("/api/clients/{client_id}/goals/{goal_id}/ideas")
def goal_ideas(client_id: str, goal_id: str, req: LangRequest):
    """The AI's ad-hoc ideas for one goal, registered as levers (slow: an LLM call). Cached per goal."""
    _client(client_id)
    from ..agent.goal_assistant import ideas
    try:
        return ideas(svc(), client_id, goal_id, req.lang, more=req.more)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/clients/{client_id}/suggest-value")
def suggest_value(client_id: str, req: ValueRequest):
    """"Suggest a value" next to a question: the AI's reasoned estimate for this client."""
    _client(client_id)
    from ..agent.goal_assistant import suggest_value as sv
    return sv(svc(), client_id, req.question, req.context, req.lang)


@app.post("/api/clients/{client_id}/facts")
def facts(client_id: str, req: FactsRequest):
    _client(client_id)
    from .. import facts as f
    return f.build(svc(), client_id, req.overrides, req.lang)


@app.post("/api/clients/{client_id}/facts/edit")
def edit_fact(client_id: str, req: FactEdit):
    _client(client_id)
    from .. import facts as f
    try:
        overrides = f.apply(svc(), client_id, req.id, req.value, req.overrides)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"overrides": overrides, "facts": f.build(svc(), client_id, overrides, req.lang)}


@app.post("/api/clients/{client_id}/facts/chat")
def facts_chat(client_id: str, req: FactsChat):
    _client(client_id)
    from .. import facts as f
    return f.chat(svc(), client_id, req.message, req.overrides, req.lang)


@app.get("/api/clients/{client_id}/facts/ai")
def facts_ai(client_id: str, lang: str = "en"):
    """The LLM's plain-words reading of the data (slow: the page loads it after the facts)."""
    _client(client_id)
    from .. import facts as f
    return f.read(svc(), client_id, lang)


@app.delete("/api/clients/{client_id}/goals/{goal_id}")
def delete_goal(client_id: str, goal_id: str):
    _client(client_id)
    return svc().delete_goal(client_id, goal_id)


@app.post("/api/clients/{client_id}/whatif", response_model=WhatIfResult)
def whatif(client_id: str, req: WhatIfRequest):
    _client(client_id)
    return svc().whatif.start(client_id, req.goal_id, req.text, req.lang, allow_llm=req.use_llm)


@app.post("/api/whatif/{session_id}/answer", response_model=WhatIfResult)
def whatif_answer(session_id: str, req: AnswerRequest):
    if session_id not in svc().whatif.sessions:
        raise HTTPException(404, "unknown session")
    return svc().whatif.answer(session_id, req.answer)


@app.get("/api/primitives")
def primitives():
    """Schemas for the no-LLM fallback form."""
    return {name: {"description": d.description, "schema": d.params.model_json_schema()} for name, d in PRIMITIVES.items()}


@app.post("/api/clients/{client_id}/levers")
def add_lever(client_id: str, lever: CustomLever):
    _client(client_id)
    return svc().add_custom_lever(client_id, lever)


@app.delete("/api/clients/{client_id}/levers/{lever_id}")
def remove_lever(client_id: str, lever_id: str):
    _client(client_id)
    svc().remove_custom_lever(client_id, lever_id)
    return {"ok": True}


# ---- the "manual API": options from other companies' assistants (mygoal/partner_api) ----
class ScenarioPaste(BaseModel):
    goal_id: str
    text: str
    lang: str = "en"


class IntegrationAsk(BaseModel):
    goal_id: str
    lang: str = "en"


class IntegrationConnect(BaseModel):
    url: str


@app.get("/api/partner-prompt")
def partner_prompt(lang: str = "en"):
    """The text the client copies into another company's chatbot. The same for everyone: it carries no client data."""
    return {"prompt": prompt(lang)}


@app.get("/api/scenario-format")
def scenario_format(lang: str = "en"):
    """For companies building a compatible API: what they receive, what they publish, what they answer."""
    return {"format": FORMAT, "you_receive": request(lang, customer_ref="<the customer's account link with you>"),
            "you_publish": descriptor("Your company", "<where to POST, relative to this description; empty = same address>"),
            "you_answer": reply_schema(), "instructions": prompt(lang)}


@app.post("/api/clients/{client_id}/scenarios/import", response_model=ImportResult)
def import_scenarios(client_id: str, req: ScenarioPaste):
    """The other assistant's answer, pasted by the client."""
    _client(client_id)
    try:
        return svc().partners.import_reply(req.text, client_id=client_id, goal_id=req.goal_id, lang=req.lang)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/clients/{client_id}/integrations")
def integrations(client_id: str, lang: str = "en"):
    """The client's connected integrations, each with exactly what we would send it."""
    _client(client_id)
    return svc().partners.view(client_id, lang)


@app.post("/api/clients/{client_id}/integrations")
def connect_integration(client_id: str, req: IntegrationConnect, lang: str = "en"):
    """Check that the address belongs to a compatible API, then add it to the client's integrations."""
    _client(client_id)
    try:
        svc().partners.connect(client_id, req.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return svc().partners.view(client_id, lang)


@app.delete("/api/clients/{client_id}/integrations/{integration_id}")
def disconnect_integration(client_id: str, integration_id: str, lang: str = "en"):
    _client(client_id)
    svc().partners.disconnect(client_id, integration_id)
    return svc().partners.view(client_id, lang)


@app.post("/api/clients/{client_id}/integrations/{integration_id}/ask", response_model=ImportResult)
def ask_integration(client_id: str, integration_id: str, req: IntegrationAsk):
    """Send the request to a connected API and turn its answer into actions."""
    _client(client_id)
    if integration_id not in svc().partners.integrations(client_id):
        raise HTTPException(404, f"unknown integration {integration_id}")
    try:
        return svc().partners.ask(client_id, req.goal_id, integration_id, req.lang)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:                      # the company's API is down or answered nonsense
        log.warning("integration %s failed: %s", integration_id, exc)
        raise HTTPException(502, f"{integration_id}: {exc}") from exc


@app.get("/api/demo-partners/{partner_id}")
def demo_partner_description(partner_id: str):
    """A demo company's published description: what makes it a compatible integration."""
    p = _demo_partner(partner_id)
    return descriptor(p["name"])


@app.post("/api/demo-partners/{partner_id}")
def demo_partner(partner_id: str, body: dict[str, Any] = Body(...)):
    """A demo company's own API: the request in, its options out (reached through the http connector)."""
    p = _demo_partner(partner_id)
    return CONNECTORS.get(p["connector"])(body, p, svc())


def _demo_partner(partner_id: str) -> dict[str, Any]:
    try:
        p = partner(svc().cfg, partner_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if p["connector"] == "http":
        raise HTTPException(404, "not a demo partner")
    return p


@app.get("/api/clients/{client_id}/advisor")
def advisor(client_id: str, goal_id: str | None = None, lang: str = "en"):
    _client(client_id)
    from ..advisor import advisor_agenda
    return advisor_agenda(svc(), client_id, goal_id, lang)


# ---- the built React app, when present ----
WEB_DIST = Path(os.environ.get("MYGOAL_WEB_DIST", ROOT / "web" / "dist"))
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = WEB_DIST / path
        return FileResponse(target if path and target.is_file() else WEB_DIST / "index.html")
