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


def test_timeline_spends_vertically_locks_savings_and_actions_move_the_chances(fresh):
    timeline, car, fund = _timeline_with_car(fresh)
    tl = timeline.build(fresh, "lena", [], {}, "en")
    d = [str(x) for x in tl["dates"]]
    i = d.index(str(car.target_date))
    assert str(tl["dates"][i + 1]) > d[i] and tl["dates"][i + 1].toordinal() - tl["dates"][i].toordinal() == 1   # same day + 1
    assert tl["free"][i] - tl["free"][i + 1] > 25_000                                     # the car money leaves at once
    j = d.index(str(fund.target_date))
    assert tl["locked"][j] == 0 and tl["locked"][j + 1] > 19_000                          # the fund is locked, not spent
    act = tl["actions"]
    if act:                                                       # the first failing goal is in focus
        focus = next(g for g in tl["goals"] if g["id"] == act["goal_id"])
        assert focus["at_risk"] and set(act["recommended"]) <= set(act["gains"])
        on = timeline.build(fresh, "lena", act["recommended"], {}, "en")
        assert on["free"] != tl["free"]                           # active actions change the chart at once
        assert next(g for g in on["goals"] if g["id"] == focus["id"])["p"] >= focus["p"]
        if focus["move_to"]:
            mv = focus["move_to"]["action"]
            moved = timeline.build(fresh, "lena", [mv], {}, "en", listed=[mv])
            row = next(g for g in moved["goals"] if g["id"] == focus["id"])
            assert row["moved"] and str(row["date"]) == str(focus["move_to"]["date"]) and row["p"] > focus["p"]


def test_german_translates_engine_texts_and_english_passes_through():
    from mygoal.explain.translate import tr, tr_unit
    assert tr("Fixed costs per month", "de") == "Fixkosten pro Monat"
    assert tr("You rent: CHF 1'650/month", "de") == "Sie wohnen zur Miete: CHF 1'650/Monat"
    assert tr("Own home in ZH", "de") == "Eigenheim in ZH"
    assert tr("Fixed costs per month", "en") == "Fixed costs per month"
    assert tr("something new", "de") == "something new"
    assert tr_unit("CHF/month", "de") == "CHF/Monat"


def test_an_investment_is_its_own_pot_with_its_own_return_and_risk(fresh):
    import numpy as np
    from mygoal.engine import simulate
    from mygoal.levers.primitives import build_primitive
    goal = fresh.goal("lena", "home")
    base, market, _ = fresh.baseline("lena")
    ctx = fresh.lever_context("lena", goal, base, {})

    def run(r, vol):
        lv = build_primitive("invest", {"title": "Trade stocks", "amount_once": {"value": 20000, "label": "Put in", "source": "user"},
                                        "expected_return": {"value": r, "label": "Return", "source": "user"},
                                        "volatility": {"value": vol, "label": "Volatility", "source": "user"}}, ctx, "whatif:t")
        return lv, simulate(base, [lv], market, 60, 1000, 3)

    lv, calm = run(0.05, 0.05)
    _, wild = run(10, 35)                                    # "10" and "35" are read as 10% and 35%
    assert {a.unit for a in lv.assumptions if a.key in ("expected_return", "volatility")} == {"%/yr"}
    none = simulate(base, [], market, 60, 1000, 3)
    assert float(np.median(calm.invested[-1] - none.invested[-1])) > 20000   # the pot counts as invested money
    spread = lambda tr_: float(np.percentile(tr_.invested[-1], 90) - np.percentile(tr_.invested[-1], 10))  # noqa: E731
    assert spread(wild) > 2 * spread(calm)


def test_only_one_retirement_goal(fresh):
    assert [g.params["retirement_age"] for g in fresh.state("lena").goals if g.type == "retirement"] == [65]
    ga.draft(fresh, "lena", "retire at 60")
    retire = [g for g in fresh.state("lena").goals if g.type == "retirement"]
    assert len(retire) == 1 and retire[0].params["retirement_age"] == 60


def test_same_category_is_the_same_idea():
    from mygoal.model import GoalSpec
    car = GoalSpec(id="a", type="target", label="Family car", params={"amount": 20000}, category="car")
    other_car = GoalSpec(id="b", type="target", label="A Ferrari", params={"amount": 180000}, category="car")
    trek = GoalSpec(id="c", type="target", label="Himalaya trek", params={"amount": 8000}, category="travel")
    assert ga._same_idea(car, other_car) and not ga._same_idea(car, trek)
    r1 = GoalSpec(id="r1", type="retirement", label="Retire at 65", params={"retirement_age": 65}, category="retirement")
    r2 = GoalSpec(id="r2", type="retirement", label="Retire early", params={"retirement_age": 60}, category="retirement")
    assert ga._same_idea(r1, r2)


def test_action_gains_stay_put_when_toggled(fresh):
    from mygoal import timeline
    ga.draft(fresh, "lena", "a car for CHF 30'000 in 2 years")
    tl = timeline.build(fresh, "lena", [], {}, "en")
    act = tl["actions"]
    assert act
    before = dict(act["gains"])
    rec = [i for i in act["recommended"] if not i.startswith("move:")][:2]
    on = timeline.build(fresh, "lena", rec, {}, "en", listed=list(before))
    assert on["actions"]
    for i, g in before.items():
        assert on["actions"]["gains"][i] == pytest.approx(g, abs=1e-9)


def test_buying_something_marks_a_chart_event_and_explains_the_monthly_figure(fresh):
    from mygoal import timeline
    from mygoal.agent.session import Session
    from mygoal.agent.tools import propose_lever
    s = Session(client_id="lena", goal_id="home", text="buy a quail farm", lang="en")
    _, err = propose_lever(fresh, s, {"title": "Quail farm", "parts": [
        {"primitive": "one_off", "params": {"amount": {"value": -25000, "label": "Farm setup", "source": "user"}, "in_months": 6}},
        {"primitive": "income_change", "params": {
            "net_monthly_delta": {"value": 350, "label": "Farm income", "source": "user"}, "taxable_side_income": True}},
    ]}, created_by="test")
    assert not err and s.lever_id
    events = timeline.build(fresh, "lena", [s.lever_id], {}, "en")["events"]
    assert any(e["amount"] >= 24000 for e in events)
    how = fresh.evaluate_lever("lena", "home", s.lever_id)["how_the_monthly_figure_comes_about"]
    assert how["notes"] and "350" in how["notes"][0]
    assert how["once"] <= -24000
    assert 0 < how["total"] < 350
    ev = fresh.evaluate_lever("lena", "home", s.lever_id)
    assert ev["monthly_equivalent"] == how["total"] or abs(ev["monthly_equivalent"] - how["total"]) < 1


def test_plan_breakdown_uses_months_until_the_goal(lena_plan):
    with_b = [c for c in lena_plan.levers if (c.details or {}).get("breakdown", {}).get("months")]
    assert with_b and all(c.details["breakdown"]["months"] > 12 for c in with_b)


def test_suggest_value_without_llm_says_unavailable(fresh):
    assert ga.suggest_value(fresh, "lena", "How much would a used car cost?") == {"available": False}
