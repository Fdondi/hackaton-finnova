"""Explicit consumer-loan actions: never auto-planned, rate sources are stated, debt is marked."""
import pytest

from mygoal.agent import goal_assistant as ga
from mygoal.levers.loan import annuity_payment, remaining_after, suggested_rate
from mygoal.service import PlanningService, PlanRequest


@pytest.fixture()
def fresh():
    return PlanningService()


def test_annuity_pays_down_to_zero():
    p, r, n = 12_000.0, 0.06, 24
    assert remaining_after(p, r, n, 0) == pytest.approx(p)
    assert remaining_after(p, r, n, n) == pytest.approx(0.0, abs=1e-6)
    assert remaining_after(p, r, n, n // 2) < p
    assert annuity_payment(p, 0.0, 12) == pytest.approx(1000.0)


def test_spend_goal_offers_a_loan_that_stays_off_until_agreed(fresh):
    from mygoal import timeline
    car = ga.draft(fresh, "lena", "a boat for CHF 90'000 in 1 year")["goal"]
    loan_id = f"loan:goal:{car.id}"
    off = fresh.plan("lena", PlanRequest(goal_id=car.id, include_cross_goal=False))
    assert loan_id not in off.plan
    card = next(c for c in off.levers if c.lever_id == loan_id)
    assert card.details["needs_agreement"]
    sources = {row["title"] for row in card.details["rate_sources"]}
    assert sources == {"Your history", "People like you", "Apparent creditworthiness"}
    notes = " ".join(card.details["notes"]).lower()
    assert "will not assume a loan" in notes or "stays off" in notes
    listed = timeline.build(fresh, "lena", [], {}, "en", listed=[loan_id], focus=car.id)
    act = listed["actions"]
    if act and act["goal_id"] == car.id:
        assert loan_id in act["optional"] and loan_id not in act["recommended"]

    on = fresh.plan("lena", PlanRequest(goal_id=car.id, active=[loan_id], include_cross_goal=False))
    assert on.scenario.p_success > off.baseline.p_success

    chart = timeline.build(fresh, "lena", [], {}, "en")
    assert all(x == 0 for x in chart.get("debt") or [0])
    borrowed = timeline.build(fresh, "lena", [loan_id], {}, "en")
    assert max(borrowed["debt"]) >= 20_000
    assert any(e.get("kind") == "loan" and e["amount"] >= 20_000 for e in borrowed["events"])


def test_home_and_savings_are_not_financed_with_a_consumer_loan(fresh):
    home = fresh.plan("lena", PlanRequest(goal_id="home", include_cross_goal=False))
    assert all(not c.lever_id.startswith("loan:") for c in home.levers)
    fund = ga.draft(fresh, "lena", "save an emergency fund of CHF 20'000 in 4 years")["goal"]
    ctx = fresh.lever_context("lena", fund, fresh.planner("lena", fund, {}).base, {})
    from mygoal.levers.loan import finance_with_loan
    assert finance_with_loan(ctx) is None


def test_purchase_loan_does_nothing_until_the_purchase_is_on(fresh):
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
    loan_id = f"loan:{s.lever_id}"
    only_loan = timeline.build(fresh, "lena", [loan_id], {}, "en")
    assert all(x == 0 for x in only_loan.get("debt") or [0])
    assert not any(e.get("kind") == "loan" for e in only_loan["events"])
    both = timeline.build(fresh, "lena", [s.lever_id, loan_id], {}, "en")
    assert max(both["debt"]) >= 20_000
    assert any(e.get("kind") == "loan" for e in both["events"])
    farm = next(e for e in both["events"] if e.get("kind") == "purchase")
    assert farm["amount"] >= 24_000


def test_suggested_rate_stays_inside_the_configured_band(fresh):
    goal = fresh.goal("lena", "world_trip")
    ctx = fresh.lever_context("lena", goal, fresh.planner("lena", goal, {}).base, {})
    rate, sources, score = suggested_rate(ctx)
    cfg = fresh.cfg["loan"]
    assert cfg["unsecured_min"] <= rate <= cfg["unsecured_max"]
    assert 0.15 <= score <= 0.92
    assert [row["title"] for row in sources] == ["Your history", "People like you", "Apparent creditworthiness"]
    peer = next(row for row in sources if row["title"] == "People like you")
    assert "no observed consumer-loan rates" in peer["text"] or "no bank-wide loan-rate data" in peer["text"]
