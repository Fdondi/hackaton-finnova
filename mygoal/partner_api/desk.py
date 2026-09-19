"""PartnerDesk: the client's integrations, and turning replies into actions (custom levers built from primitives).

A reply arrives two ways and is handled the same: pasted by the client, or returned by a connected API. Every figure
a partner sends is tagged source "partner" (it can never pass as the bank's own data). A scenario that doesn't
validate comes back with a correction text the client can give to the other assistant. The result carries exactly
what was sent and received, so the page can show it.
"""
from __future__ import annotations

import re
import threading
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from ..agent.session import Session
from ..agent.tools import propose_lever
from ..levers import PRIMITIVES
from .connectors import CONNECTORS, discover, partners
from .contract import EXCLUDED_PRIMITIVES, FORMAT, GROUPS, parse_reply, request

if TYPE_CHECKING:
    from ..service import PlanningService

EFFORTS = ("none", "low", "medium", "high")


class ImportResult(BaseModel):
    source: str
    via: str                                               # "paste" or "api:<integration id>"
    ids: list[str] = Field(default_factory=list)          # the new actions (custom lever ids)
    titles: list[str] = Field(default_factory=list)
    rejected: list[dict[str, str]] = Field(default_factory=list)   # {"title", "error"}
    fix_prompt: str | None = None                          # hand this back to the other assistant
    note: str = ""
    pick_one: bool = False
    sent: dict[str, Any] | None = None                     # exactly what we sent (integrations)
    received: Any = None                                   # exactly what came back, as JSON


def _estimate(v: Any, name: str) -> Any:
    """A partner's number as an Estimate tagged "partner" (a plain number is a firm figure)."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        v = {"value": v}
    if isinstance(v, dict) and "value" in v:
        v = {**v, "source": "partner"}
        v.setdefault("label", name.replace("_", " ").capitalize())
    return v


def normalize(sc: Any) -> dict[str, Any]:
    """One scenario from the reply -> a lever proposal for propose_lever. Raises ValueError for what can't be fixed here."""
    if not isinstance(sc, dict):
        raise ValueError("each scenario must be a JSON object")
    parts = []
    for i, part in enumerate(sc.get("parts") or []):
        if not isinstance(part, dict):
            raise ValueError(f"part {i} must be a JSON object")
        name = str(part.get("primitive") or "")
        if name in EXCLUDED_PRIMITIVES:
            raise ValueError(f"part {i}: the building block {name} is not available here")
        if name not in PRIMITIVES:
            raise ValueError(f"part {i}: unknown building block '{name}'")
        params = part.get("params") or {k: v for k, v in part.items() if k not in ("primitive", "params")}
        model = PRIMITIVES.get(name).params
        params = {k: _estimate(v, k) if k in model.model_fields and "Estimate" in str(model.model_fields[k].annotation) else v
                  for k, v in params.items()}
        parts.append({"primitive": name, "params": params})
    if not parts:
        raise ValueError("an option needs at least one part")
    side = [str(x)[:200] for x in (sc.get("side_effects") or []) if x][:5]
    if side:
        parts[0]["params"]["side_effects"] = [*parts[0]["params"].get("side_effects", []), *side]
    return {"title": str(sc.get("title") or "")[:80], "description": str(sc.get("description") or "")[:300],
            "group": sc.get("group") if sc.get("group") in GROUPS else "structural",
            "effort": sc.get("effort") if sc.get("effort") in EFFORTS else "medium", "parts": parts}


def fix_text(rejected: list[dict[str, str]]) -> str:
    lines = "\n".join(f"- {r['title'] or 'Reply'}: {r['error']}" for r in rejected)
    return (f"Thanks! My bank's planning tool couldn't read some of it:\n{lines}\n\n"
            f"Please send the whole JSON again with these fixed (same format, \"format\": \"{FORMAT}\").")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:32] or "partner"


class PartnerDesk:
    def __init__(self, svc: "PlanningService"):
        self.svc = svc
        self._integrations: dict[str, dict[str, dict[str, Any]]] = {}   # client id -> integration id -> integration
        self.lock = threading.Lock()

    # ---- integrations ----
    def integrations(self, client_id: str) -> dict[str, dict[str, Any]]:
        """The client's connected integrations; the first time, the ones they connected before (config: activated)."""
        with self.lock:
            if client_id not in self._integrations:
                self._integrations[client_id] = {p["id"]: dict(p) for p in partners(self.svc.cfg) if p.get("activated")}
            return self._integrations[client_id]

    def view(self, client_id: str, lang: str = "en") -> dict[str, Any]:
        """For the page: each integration with where it goes and exactly what we would send it, and the demo companies
        that could be connected (their description is served at /api/demo-partners/<id>)."""
        mine = self.integrations(client_id)
        names = {p["name"] for p in mine.values()}
        return {"connected": [{"id": i, "name": p["name"], "url": p.get("url"), "built_in": p.get("connector") != "http",
                               "sends": request(lang, customer_ref=client_id)} for i, p in mine.items()],
                "demo_addresses": [f"/api/demo-partners/{p['id']}" for p in partners(self.svc.cfg)
                                   if p.get("connector") != "http" and p["name"] not in names]}

    def connect(self, client_id: str, url: str) -> dict[str, Any]:
        """Check that the address belongs to a compatible API and add it to the client's integrations."""
        desc, endpoint = discover(url)
        name = " ".join(str(desc["name"]).split())[:60]
        integration = {"id": f"api_{_slug(name)}", "name": name, "connector": "http", "url": endpoint, "added_from": url.strip()}
        self.integrations(client_id)[integration["id"]] = integration
        return integration

    def reset(self, client_id: str) -> None:
        with self.lock:
            self._integrations.pop(client_id, None)   # back to the ones connected in the config

    def disconnect(self, client_id: str, integration_id: str) -> None:
        self.integrations(client_id).pop(integration_id, None)

    def ask(self, client_id: str, goal_id: str, integration_id: str, lang: str = "en") -> ImportResult:
        """Send the request to a connected API and turn its reply into actions."""
        p = self.integrations(client_id)[integration_id]
        # demo: the account link between the client and the company is the client id (a real one: a consent token)
        sent = request(lang, customer_ref=client_id)
        reply = CONNECTORS.get(p["connector"])(sent, p, self.svc)
        result = self.import_reply(reply, client_id=client_id, goal_id=goal_id, lang=lang, via=f"api:{integration_id}",
                                   default_source=p["name"])
        result.sent = sent
        return result

    # ---- replies ----
    def import_reply(self, payload: str | dict | list, *, client_id: str, goal_id: str, lang: str = "en", via: str = "paste",
                     default_source: str = "Another assistant") -> ImportResult:
        self.svc.goal(client_id, goal_id)                      # KeyError for an unknown goal
        received = parse_reply(payload) if isinstance(payload, str) else payload
        data = {"scenarios": received} if isinstance(received, list) else received
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object with "scenarios"')
        if "scenarios" not in data and "parts" in data:            # a single scenario on its own
            data = {"scenarios": [data]}
        source = " ".join(str(data.get("source") or default_source).split())[:60]
        pick_one = bool(data.get("pick_one"))
        st = self.svc.state(client_id)

        ids, titles, rejected = [], [], []
        scenarios = data.get("scenarios") or []
        if not isinstance(scenarios, list) or not scenarios:
            rejected.append({"title": "", "error": 'no options found: expected {"scenarios": [...]}'})
            scenarios = []
        for i, sc in enumerate(scenarios):
            title = str((sc.get("title") if isinstance(sc, dict) else "") or "")[:80] or f"Option {i + 1}"
            try:
                args = normalize(sc)
            except ValueError as exc:
                rejected.append({"title": title, "error": str(exc)})
                continue
            args["title"] = args["title"] or title
            s = Session(client_id=client_id, goal_id=goal_id, text=title, lang=lang)
            # asked again: the same company's option of the same name replaces the old one instead of piling up
            s.lever_id = next((cl.lever_id for cl in st.custom_levers.values() if cl.source == source and cl.title == args["title"]), None)
            msg, err = propose_lever(self.svc, s, args, created_by=f"partner:{via}", prefix="scenario", source=source)
            if err or not s.lever_id:
                rejected.append({"title": title, "error": msg[:400]})
            else:
                ids.append(s.lever_id)
                titles.append(args["title"])
        if pick_one and len(ids) > 1:                              # alternatives: switching one on switches the others off
            for i in ids:
                st.custom_levers[i].excludes = [j for j in ids if j != i]
            st.version += 1
        return ImportResult(source=source, via=via, ids=ids, titles=titles, rejected=rejected,
                            fix_prompt=fix_text(rejected) if rejected else None, note=str(data.get("note") or "")[:300],
                            pick_one=pick_one, received=received)
