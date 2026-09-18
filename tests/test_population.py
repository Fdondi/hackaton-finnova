"""Testdata adapter, population risk and life-event evidence.

Engine checks run on the synthetic persona (always present). Checks that need the prepared testdata skip when
data/testdata is missing (run scripts/prep_testdata.py).
"""
import copy
import dataclasses
import json
import math
from datetime import date

import numpy as np
import pytest

from mygoal.config import ROOT, load_config
from mygoal.engine import simulate
from mygoal.model import add_months

TESTDATA = ROOT / "data" / "testdata"
needs_testdata = pytest.mark.skipif(not (TESTDATA / "meta.json").exists(), reason="run scripts/prep_testdata.py first")


@pytest.fixture(scope="module")
def tsvc():
    from mygoal.service import PlanningService
    cfg = copy.deepcopy(load_config())
    cfg["app"]["data"].update(source="testdata", dir=str(TESTDATA), shift_to_today=True)
    return PlanningService(cfg)


@pytest.fixture(scope="module")
def demo_id():
    return json.loads((TESTDATA / "shortlist.json").read_text(encoding="utf-8"))[0]["id"]


# ---- engine: one-off bills (runs everywhere) ----
def test_bill_shocks_keep_the_mean_and_widen_the_spread(svc):
    base, market, _ = svc.baseline("lena")
    T, N, seed = 120, 2000, 7
    off = simulate(base, [], market, T, N, seed)
    assert market.bill_rate == 0.0                                   # synthetic persona: no population data, no shocks
    rate, mu, sigma = 2.0, 7.6, 0.7
    mean_monthly = rate * math.exp(mu + sigma**2 / 2) / 12
    shocked = simulate(base.model_copy(update={"variable_costs_monthly": base.variable_costs_monthly - mean_monthly}), [],
                       dataclasses.replace(market, bill_rate=rate, bill_mu=mu, bill_sigma=sigma), T, N, seed)
    end_off, end_on = off.cash[-1], shocked.cash[-1]
    assert abs(end_on.mean() - end_off.mean()) / abs(end_off.mean()) < 0.03
    assert end_on.std() > end_off.std()


# ---- adapter ----
@needs_testdata
def test_testdata_client_loads_with_shifted_dates_and_clean_categories(tsvc, demo_id):
    st = tsvc.state(demo_id)
    ds, p = st.ds, st.profile
    assert len(ds.bookings) > 100 and ds.source == "testdata"
    last_month = add_months(date.today().replace(day=1), -1)
    assert (ds.as_of.year, ds.as_of.month) == (last_month.year, last_month.month)
    cats = {b.category for b in ds.bookings}
    assert {"income_salary", "housing", "internal_transfer"} <= cats
    fallback = sum(b.category_source == "fallback" for b in ds.bookings) / len(ds.bookings)
    assert fallback < 0.05
    assert st.goals, "goals are seeded from config/goal_seeds.yaml"
    assert any(n.level == "info" and "moved forward" in n.message for n in p.data_quality)


@needs_testdata
def test_population_risk_is_calibrated_and_labelled(tsvc, demo_id):
    st = tsvc.state(demo_id)
    assert st.risk is not None and st.risk.bill_rate > 0
    _, market, assumptions = tsvc.baseline(demo_id)
    assert market.bill_rate == pytest.approx(st.risk.bill_rate)
    assert any(a.key == "big_bill_rate" and a.source == "population" for a in assumptions)
    risk = tsvc.overview(demo_id)["risk"]
    assert risk["bad_year"] > 0 and len(risk["texts"]) >= 6


# ---- life events ----
def test_life_event_levers_stay_off_without_population_data(svc):
    from mygoal.specialists.life_events import job_change, separation, wedding
    from mygoal.specialists.family import have_child
    st = svc.state("lena")
    goal = st.goals[0]
    base, _, _ = svc.baseline("lena")
    ctx = svc.lever_context("lena", goal, base, {})
    assert wedding(ctx) is None and separation(ctx) is None and job_change(ctx) is None
    child = have_child(ctx)
    assert child is None or all(a.source != "population" for a in child.assumptions)


@needs_testdata
def test_birth_evidence_calibrates_have_child(tsvc, demo_id):
    from mygoal.specialists.family import have_child
    pop = tsvc.services["population"]
    ev = pop.life_event("birth")
    assert ev is not None and ev["n"] >= 20
    st = tsvc.state(demo_id)
    base, _, _ = tsvc.baseline(demo_id)
    child = have_child(tsvc.lever_context(demo_id, st.goals[0], base, {}))
    if child is not None:
        costs = next(a for a in child.assumptions if a.key == "child_costs_monthly")
        assert costs.source == "population" and costs.value == pytest.approx(ev["d_spend"]["median"], rel=0.31)


@needs_testdata
def test_evidence_tool_reports_people_and_costs(tsvc):
    from mygoal.agent.tools import life_event_evidence
    r = life_event_evidence(tsvc, "wedding")
    assert r["available"] and r["people"] >= 20 and r["costs_around_the_event"]["median_if_any"] > 10_000
    assert life_event_evidence(tsvc, "moon_landing")["available"] is False
    assert np.isfinite(r["monthly_spending_change"]["median"])
