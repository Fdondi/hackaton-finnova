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
    assert r["status"] == "goal" and r["goal"].params["amount"] == 30_000 and r["goal"].status == "confirmed"
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


def test_deleted_suggestions_stay_deleted_and_goal_dates_are_june(fresh, monkeypatch):
    monkeypatch.setattr(ga, "rule_suggestions", lambda svc, cid: [
        {"type": "target", "label": "A sports car", "amount": 180_000, "years": 2, "reason": "test"}])
    goals = ga.suggest(fresh, "lena", "en", use_llm=False)
    idea = next(g for g in goals if g.status == "suggested")
    fresh.delete_goal("lena", idea.id)
    again = ga.suggest(fresh, "lena", "en", use_llm=False)
    assert all(g.label != idea.label for g in again)
    r = ga.draft(fresh, "lena", "a boat for CHF 60'000 in 3 years")
    assert r["goal"].target_date.month == 6 and r["goal"].target_date.day == 1


def _timeline_with_car(fresh):
    from mygoal import timeline
    car = ga.draft(fresh, "lena", "a car for CHF 30'000 in 2 years")["goal"]
    fund = ga.draft(fresh, "lena", "save an emergency fund of CHF 20'000 in 4 years")["goal"]
    assert fund.params["kind"] == "save"
    return timeline, car, fund


def test_timeline_spends_vertically_locks_savings_and_previews_without_touching_the_chart(fresh):
    timeline, car, fund = _timeline_with_car(fresh)
    tl = timeline.build(fresh, "lena", [], {}, "en")
    d = [str(x) for x in tl["dates"]]
    i = d.index(str(car.target_date))
    assert str(tl["dates"][i + 1]) > d[i] and tl["dates"][i + 1].toordinal() - tl["dates"][i].toordinal() == 1   # same day + 1
    assert tl["free"][i] - tl["free"][i + 1] > 25_000                                     # the car money leaves at once
    j = d.index(str(fund.target_date))
    assert tl["locked"][j] == 0 and tl["locked"][j + 1] > 19_000                          # the fund is locked, not spent
    risky = [g for g in tl["goals"] if g["at_risk"]]
    if risky:
        g = risky[0]
        prev = timeline.build(fresh, "lena", [], {}, "en", preview={g["id"]: g["proposal"]})
        assert prev["free"] == tl["free"]                                                  # preview: chart unchanged
        acc = timeline.build(fresh, "lena", g["proposal"], {}, "en")
        assert next(x for x in acc["goals"] if x["id"] == g["id"])["p"] >= g["p"]


def test_german_translates_engine_texts_and_english_passes_through():
    from mygoal.explain.translate import tr, tr_unit
    assert tr("Fixed costs per month", "de") == "Fixkosten pro Monat"
    assert tr("You rent: CHF 1'650/month", "de") == "Sie wohnen zur Miete: CHF 1'650/Monat"
    assert tr("Own home in ZH", "de") == "Eigenheim in ZH"
    assert tr("Fixed costs per month", "en") == "Fixed costs per month"
    assert tr("something new", "de") == "something new"
    assert tr_unit("CHF/month", "de") == "CHF/Monat"


def test_an_investment_strategy_changes_return_and_risk(fresh):
    import dataclasses
    import numpy as np
    from mygoal.engine import simulate
    base, market, _ = fresh.baseline("lena")
    base = base.model_copy(update={"invested": 50_000.0})
    impact = fresh.levers("lena", fresh.goal("lena", "home"), base, {})[0].model_copy(
        update={"settings": {"portfolio_return": 0.10, "portfolio_volatility": 0.35}, "recurring": [], "one_offs": [],
                "income_changes": [], "allocation_changes": [], "goal_changes": [], "shocks": []})
    calm = simulate(base, [], market, 120, 1000, 3)
    wild = simulate(base, [impact], dataclasses.replace(market), 120, 1000, 3)
    spread = lambda tr_: float(np.percentile(tr_.invested[-1], 90) - np.percentile(tr_.invested[-1], 10))  # noqa: E731
    assert spread(wild) > spread(calm)
