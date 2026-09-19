"""The "manual API": options from other companies' assistants become actions in the plan.

The client copies a fixed text into another company's chatbot, where they are logged in ("from your point of view,
with the information you have about the logged-in user, describe the options you recommend, in this format"), and
pastes the JSON answer back. Companies whose API speaks the format are integrations: connected once from their address
(we check it's compatible), then asked with one click. Nothing we send carries client data beyond an integration's
account link, and the page shows exactly what goes out and what comes back.

    contract.py      the format ("mygoal.scenarios/v1"), the copy text, what we send, what a compatible API publishes
    desk.py          PartnerDesk: the client's integrations, replies -> actions (validation, correction text)
    connectors.py    config/partners.yaml, the @connector registry, the HTTP connector, compatibility check
    mock_insurer.py  demo insurers answering with health-insurance plan alternatives
"""
from .connectors import CONNECTORS, connector, partner, partners
from .contract import FORMAT, ScenarioReply, descriptor, prompt, reply_schema, request
from .desk import ImportResult, PartnerDesk

__all__ = ["CONNECTORS", "connector", "partner", "partners", "FORMAT", "ScenarioReply", "descriptor", "prompt", "reply_schema",
           "request", "ImportResult", "PartnerDesk"]
