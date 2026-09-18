"""What-if without an LLM: the rules agent must produce valid, labelled levers."""


def test_warhammer_whatif(svc):
    w = svc.whatif
    r = w.start("lena", "home", "What if I sell my Warhammer collection?")
    assert r.status == "question" and r.agent == "rules"
    assert "games workshop" in " ".join(s.summary.lower() for s in r.steps)
    r = w.answer(r.session_id, "1200")
    assert r.status == "lever" and r.lever_id
    lever = svc.state("lena").custom_levers[r.lever_id]
    assert lever.parts[0]["primitive"] == "asset_dispose"
    assert r.evaluation["monthly_equivalent"] > 0


def test_specialist_routing(svc):
    r = svc.whatif.start("lena", "home", "What if I got rid of the car?")
    assert r.status == "existing_lever" and r.lever_id == "give_up_car"


def test_agent_levers_need_ranges(svc):
    from mygoal.agent.session import Session
    from mygoal.agent.tools import propose_lever
    s = Session(client_id="lena", goal_id="home", text="x", lang="en")
    msg, err = propose_lever(svc, s, {"title": "Sell boat", "parts": [{"primitive": "asset_dispose", "params": {
        "asset": "boat", "sale_value": {"value": 20000, "source": "llm_estimate", "label": "Boat sale"},
        "running_costs_monthly": {"value": 300, "source": "user", "label": "Boat costs"}}}]}, created_by="test")
    assert err and "low and high" in msg


def test_unsupported_is_honest(svc):
    r = svc.whatif.start("lena", "home", "Tell me a joke")
    assert r.status == "unsupported"
