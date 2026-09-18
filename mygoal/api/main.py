"""HTTP API. Thin: every endpoint is one call into PlanningService. OpenAPI docs at /docs.

    uv run uvicorn mygoal.api.main:app --reload --port 8080
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..agent import WhatIfResult
from ..config import ROOT
from ..levers import PRIMITIVES
from ..llm import llm_status
from ..model import GoalSpec
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


class DraftRequest(BaseModel):
    text: str
    lang: str = "en"
    question: str | None = None
    answer: str | None = None


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


@app.get("/api/clients/{client_id}/goals")
def goals(client_id: str):
    return _client(client_id).goals


@app.post("/api/clients/{client_id}/goals/suggest")
def suggest_goals(client_id: str, req: LangRequest):
    """Rules on the data plus (once per client) the LLM's ideas, added as suggested goals."""
    _client(client_id)
    from ..agent.goal_assistant import suggest
    return suggest(svc(), client_id, req.lang, use_llm=req.use_llm)


@app.post("/api/clients/{client_id}/goals/draft")
def draft_goal(client_id: str, req: DraftRequest):
    """One sentence -> a suggested goal, or one question first."""
    _client(client_id)
    from ..agent.goal_assistant import draft
    return draft(svc(), client_id, req.text, req.lang, req.question, req.answer)


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
