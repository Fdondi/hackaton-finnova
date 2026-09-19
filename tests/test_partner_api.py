"""The "manual API": options from other companies' assistants become actions (mygoal/partner_api)."""
import json

import pytest
from fastapi.testclient import TestClient

from mygoal.partner_api import connectors
from mygoal.partner_api.contract import EXCLUDED_PRIMITIVES, FORMAT, parse_reply, prompt
from mygoal.service import PlanningService


@pytest.fixture()
def fresh():
    return PlanningService()


@pytest.fixture()
def http(fresh, monkeypatch):
    """The API on a fresh service; the backend's own outgoing calls (to demo partners) go to the same test client."""
    from mygoal.api import main
    monkeypatch.setattr(main, "svc", lambda: fresh)
    client = TestClient(main.app)
    local = lambda url: url.replace("http://testserver", "")   # noqa: E731
    monkeypatch.setattr(connectors, "get_json", lambda url, timeout=5: client.get(local(url)).json())
    monkeypatch.setattr(connectors, "post_json", lambda url, body, timeout=30: client.post(local(url), json=body).json())
    return client


def test_the_copy_text_asks_for_options_in_the_format_and_carries_no_client_data(fresh):
    text = prompt("en")
    assert text.startswith("From your point of view, with the information you have about the logged-in user")
    assert FORMAT in text and "replace_spending" in text and not any(f"- {n}:" in text for n in EXCLUDED_PRIMITIVES)
    assert "http" not in text                                   # nowhere to post to: the client pastes the answer back
    st = fresh.state("lena")
    for private in (st.ds.client.name, st.ds.client.canton, f"{round(st.profile.balances.liquid)}"):
        assert private and private not in text


def test_a_pasted_answer_becomes_partner_actions_and_bad_options_come_back_with_a_correction_text(fresh):
    reply = {"source": "Some chatbot", "scenarios": [
        {"title": "Cheaper phone plan", "parts": [{"primitive": "replace_spending", "category": "utilities", "new_monthly": 25}]},
        {"title": "Claims to be bank data", "parts": [{"primitive": "one_off", "amount": {"value": 500, "label": "Gift",
                                                                                         "source": "transactions"}}]},
        {"title": "Moves the goal", "parts": [{"primitive": "goal_change", "field": "price", "value": 1}]},
        {"title": "No price", "parts": [{"primitive": "replace_spending", "category": "utilities"}]},
    ]}
    r = fresh.partners.import_reply("Here you go!\n```json\n" + json.dumps(reply) + "\n```", client_id="lena", goal_id="home")
    assert r.source == "Some chatbot" and len(r.ids) == 2 and all(i.startswith("scenario:") for i in r.ids)
    assert [x["title"] for x in r.rejected] == ["Moves the goal", "No price"] and r.fix_prompt
    assert r.received == reply and r.sent is None                 # the page shows exactly what came back

    goal = fresh.goal("lena", "home")
    levers = {lv.lever_id: lv for lv in fresh.levers("lena", goal, fresh.planner("lena", goal, {}).base, {})}
    phone, gift = levers[r.ids[0]], levers[r.ids[1]]
    assert phone.origin == gift.origin == "partner" and phone.details["partner"] == "Some chatbot"
    today = next(a for a in phone.assumptions if a.key == "current_monthly")
    assert today.source == "transactions" and today.value == pytest.approx(fresh.state("lena").profile.monthly("utilities"), abs=0.01)
    assert {a.source for a in gift.assumptions} == {"partner"}      # a partner can't pass figures off as bank data


def test_a_connected_insurer_answers_with_alternatives_that_exclude_each_other(fresh):
    assert list(fresh.partners.integrations("lena")) == ["alpenschutz"]     # connected before: listed right away
    r = fresh.partners.ask("lena", "home", "alpenschutz", "de")
    assert len(r.ids) >= 3 and r.pick_one and not r.rejected and any("Franchise" in t for t in r.titles)
    assert set(r.sent) == {"format", "request", "language", "customer_ref"}  # all we send
    st = fresh.state("lena")
    for i in r.ids:
        assert sorted(st.custom_levers[i].excludes) == sorted(j for j in r.ids if j != i)
    goal = fresh.goal("lena", "home")
    pl = fresh.planner("lena", goal, {})
    options = [lv for lv in fresh.levers("lena", goal, pl.base, {}) if lv.lever_id in r.ids]
    assert len(pl.auto_plan(options, fresh.cfg["app"]["planning"]["effort_weight"])) <= 1   # never two plan variants at once
    assert fresh.partners.ask("lena", "home", "alpenschutz", "de").ids == r.ids             # asked again: updated, no duplicates


def test_a_new_integration_is_connected_from_its_address_only_when_compatible(http):
    before = http.get("/api/clients/lena/integrations").json()
    assert [c["id"] for c in before["connected"]] == ["alpenschutz"] and "/api/demo-partners/rigi" in before["demo_addresses"]
    assert http.post("/api/clients/lena/integrations", json={"url": "http://testserver/api/health"}).status_code == 422
    assert http.post("/api/clients/lena/integrations", json={"url": "file:///etc/passwd"}).status_code == 422
    after = http.post("/api/clients/lena/integrations", json={"url": "http://testserver/api/demo-partners/rigi"}).json()
    rigi = next(c for c in after["connected"] if c["name"].startswith("Rigi"))
    assert rigi["url"] == "http://testserver/api/demo-partners/rigi" and not after["demo_addresses"]
    r = http.post(f"/api/clients/lena/integrations/{rigi['id']}/ask", json={"goal_id": "home"}).json()
    assert r["ids"] and not r["rejected"] and r["received"]["scenarios"][0]["parts"][0]["primitive"] == "replace_spending"
    gone = http.delete(f"/api/clients/lena/integrations/{rigi['id']}").json()
    assert [c["id"] for c in gone["connected"]] == ["alpenschutz"]


def test_answers_are_read_from_chatty_replies():
    assert parse_reply('Sure:\n```json\n{"scenarios": []}\n```\nAnything else?') == {"scenarios": []}
    assert parse_reply('Here: {"a": [1, 2]} hope it helps') == {"a": [1, 2]}
    with pytest.raises(ValueError):
        parse_reply("no json here")
