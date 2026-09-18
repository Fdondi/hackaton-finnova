"""Goals page and facts page backends, without an LLM (rules and fallbacks). A fresh service: these tests mutate state."""
import pytest

from mygoal.agent import goal_assistant as ga
from mygoal.service import PlanningService, PlanRequest


@pytest.fixture()
def fresh():
    return PlanningService()


def test_suggestions_are_added_as_unconfirmed_goals(fresh):
    before = {g.id for g in fresh.state("lena").goals}
    goals = ga.suggest(fresh, "lena", "en", use_llm=False)
    new = [g for g in goals if g.id not in before]
    assert all(g.status == "confirmed" for g in goals if g.id in before)      # the persona's own goals stay confirmed
    assert all(g.status == "suggested" and g.origin == "data" and g.note for g in new)


def test_one_sentence_becomes_a_goal_with_at_most_one_question(fresh):
    r = ga.draft(fresh, "lena", "a car for CHF 30'000 in 2 years")
    assert r["status"] == "goal" and r["goal"].params["amount"] == 30_000 and r["goal"].status == "suggested"
    q = ga.draft(fresh, "lena", "I want to buy a car")
    assert q["status"] == "question"
    a = ga.draft(fresh, "lena", "I want to buy a car", question=q["question"], answer="about 25k")
    assert a["status"] == "goal" and a["goal"].params["amount"] == 25_000 and a["goal"].label == "Buy a car"


def test_cross_goal_ignores_suggestions(fresh):
    ga.draft(fresh, "lena", "a boat for CHF 90'000 in 1 year")
    plan = fresh.plan("lena", PlanRequest(goal_id="home", include_cross_goal=True))
    assert all(x.goal_id != "boat" and "boat" not in x.goal_id for x in plan.cross_goal)


def test_facts_money_adds_up_and_edits_apply(fresh):
    from mygoal import facts
    f = facts.build(fresh, "lena")
    s = f["summary"]
    assert s["money_in"] - s["money_out"] == pytest.approx(s["free_cash"], abs=1)
    assert any(x["id"] == "a:gross_income_annual" and x["editable"] for x in f["money"])   # Lena: from bank records

    o = facts.apply(fresh, "lena", "a:gross_income_annual", 120_000, {"global": {}, "max_3a": {"x": 1}})
    assert o["global"]["gross_income_annual"] == 120_000 and o["max_3a"] == {"x": 1}
    edited = facts.build(fresh, "lena", o)
    assert next(x for x in edited["money"] if x["id"] == "a:gross_income_annual")["kind"] == "yours"

    kids = len(fresh.state("lena").ds.client.household.children_birth_years)
    facts.apply(fresh, "lena", "h:children", kids + 1, o)
    assert len(fresh.state("lena").ds.client.household.children_birth_years) == kids + 1

    facts.apply(fresh, "lena", "n:new", "We plan to move to Bern", o)
    note = fresh.state("lena").notes[0]
    facts.apply(fresh, "lena", f"n:{note['id']}", "", o)
    assert fresh.state("lena").notes == []


def test_facts_chat_without_llm_keeps_the_message_as_a_note(fresh):
    from mygoal import facts
    r = facts.chat(fresh, "lena", "We're expecting twins", {}, "en")
    assert r["facts"]["notes"][0]["display"] == "We're expecting twins" and r["changed"] == []
