"""The scenario format ("mygoal.scenarios/v1"): the prompt the client copies, what we send an integration, what comes back.

The other assistant (an insurer's chatbot, a chat about a side business) already knows the client: they are logged
in there. So nothing we send carries client data, only the question and the format. Both directions stay small and
flat so the client can read exactly what is transferred:

    we send       {"format", "request", "language"} (+ "customer_ref" for an API the client connected: their account link)
    we get back   {"format", "source", "pick_one", "note", "scenarios": [{"title", ..., "parts": [{"primitive", ...fields}]}]}

A scenario is built from the lever primitives the what-if agent uses, so the engine computes its effect.
A company's API is compatible when it publishes a description (see `descriptor`) at an address the client pastes,
or at https://<their host>/.well-known/mygoal-scenarios.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..agent.tools import primitive_catalogue
from ..levers import PRIMITIVES

FORMAT = "mygoal.scenarios/v1"
WELL_KNOWN = "/.well-known/mygoal-scenarios"
# the client's goals, own accounts and borrowing from the bank are not a partner's business
EXCLUDED_PRIMITIVES = ("goal_change", "reallocate", "loan")
GROUPS = ("no_lifestyle_cost", "structural", "behavioural")
LANGUAGES = {"en": "English", "de": "German"}

REQUEST = {
    "en": "From your point of view, with the information you have about the logged-in user, describe the options you "
          "recommend, in this format.",
    "de": "Beschreiben Sie aus Ihrer Sicht, mit den Informationen, die Sie über die angemeldete Person haben, die Optionen, "
          "die Sie empfehlen, in diesem Format.",
}
NUMBERS = ("Estimate = a plain number for a firm figure (your price, a quote), or {value: number, low?: number, high?: number, "
           "label: string, unit?: string} when it is uncertain or needs a name.")


class Scenario(BaseModel):
    title: str = Field(description="Short action, max 60 characters")
    description: str = Field("", description="One plain sentence: what changes and the main catch")
    effort: Literal["none", "low", "medium", "high"] = "medium"
    side_effects: list[str] = Field(default_factory=list, description="Conditions or downsides: notice periods, less cover, ...")
    parts: list[dict[str, Any]] = Field(min_length=1, description='[{"primitive": name, ...its fields}]')


class ScenarioReply(BaseModel):
    """What comes back: pasted by the client, or returned by a connected API."""
    format: str = FORMAT
    source: str = Field("", description="Who answers, e.g. 'Alpenschutz customer assistant'")
    pick_one: bool = Field(False, description="True if the client can choose only one of the scenarios (plan variants)")
    note: str = Field("", description="Optional sentence for the client: deadlines, next steps")
    scenarios: list[Scenario]


def request(lang: str = "en", customer_ref: str | None = None) -> dict[str, Any]:
    """Everything an integration receives. `customer_ref` is the account link the client set up with that company."""
    out = {"format": FORMAT, "request": REQUEST.get(lang, REQUEST["en"]), "language": lang}
    if customer_ref is not None:
        out["customer_ref"] = customer_ref
    return out


def descriptor(name: str, endpoint: str = "") -> dict[str, Any]:
    """What a compatible API publishes: the format it speaks, its name, and where to POST the request ("" = here)."""
    return {"format": FORMAT, "name": name, "endpoint": endpoint}


def reply_schema() -> dict[str, Any]:
    return ScenarioReply.model_json_schema()


FORMAT_TEXT = """Answer with one JSON block and nothing else. My bank's planning tool reads it and simulates how each \
option affects my savings and goals.
{{
  "format": "{format}",
  "source": "who you are, e.g. 'Alpenschutz customer assistant'",
  "pick_one": true if I can choose only one of the options (e.g. plan variants), false if they can be combined,
  "note": "optional: one sentence for me (deadlines, what to do next)",
  "scenarios": [
    {{
      "title": "short action, max 60 characters",
      "description": "one plain sentence: what changes and the main catch",
      "effort": "none|low|medium|high",
      "side_effects": ["conditions or downsides, e.g. notice periods, less cover"],
      "parts": [{{"primitive": "replace_spending", "category": "insurance_other", "new_monthly": {{"value": 28, "label": "New premium"}}}}]
    }}
  ]
}}

Rules:
- Each option is a change compared with what I do today; don't include "keep everything as it is".
- Amounts are CHF in today's money.
- If an option replaces something I already pay (an insurance premium, a contract) and you don't know what I pay today, \
use replace_spending: give the new price and my bank reads today's cost from my account. If you do know it, use substitute.
- An option can have several parts (e.g. a new premium plus an expected change in out-of-pocket costs).
- Write title, description, side effects and note in {language}.

Building blocks (each part is {{"primitive": name, ...its fields}}):
{catalogue}"""


def prompt(lang: str = "en") -> str:
    """The text the client copies into another assistant's chat. The same for every client: it carries no data."""
    return REQUEST.get(lang, REQUEST["en"]) + "\n\n" + FORMAT_TEXT.format(
        format=FORMAT, language=LANGUAGES.get(lang, "English"),
        catalogue=primitive_catalogue(EXCLUDED_PRIMITIVES, NUMBERS, skip=("side_effects", "title", "description", "group", "effort")))


def parse_reply(text: str) -> Any:
    """The JSON in a pasted answer: tolerates code fences and chatter around it."""
    s = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not starts:
        raise ValueError("No JSON found in the answer")
    try:
        return json.JSONDecoder().raw_decode(s[min(starts):])[0]
    except json.JSONDecodeError as exc:
        raise ValueError(f"The JSON could not be read: {exc}") from exc
