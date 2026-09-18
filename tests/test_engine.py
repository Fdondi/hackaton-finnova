"""Engine invariants and golden numbers for the demo persona."""
from datetime import date

from mygoal.engine.solve import Planner
from mygoal.goals.home import max_mortgage
from mygoal.model import LeverImpact, RecurringDelta, fixed


def test_affordability_formula():
    m = {"imputed_interest_rate": 0.05, "maintenance_rate": 0.01, "max_cost_to_income": 1 / 3,
         "second_mortgage_to_ltv": 2 / 3, "amortisation_years": 15}
    price, gross = 600000.0, 120000.0
    M = float(max_mortgage(price, gross, m, 15))
    cost = 0.05 * M + 0.01 * price + max(0.0, M - 2 / 3 * price) / 15
    assert abs(cost - gross / 3) < 1.0


def test_more_saving_never_hurts(svc):
    goal = svc.goal("lena", "home")
    pl = svc.planner("lena", goal, {})
    ps = [pl.p_success([LeverImpact(lever_id=f"x{k}", title="x", recurring=[RecurringDelta(start=pl.base.start, monthly=fixed(k))])])
          for k in (0, 300, 600, 1200)]
    assert ps == sorted(ps)


def test_common_random_numbers_are_stable(svc):
    goal = svc.goal("lena", "home")
    pl = svc.planner("lena", goal, {})
    a = Planner(pl.base, pl.market, goal, svc.cfg)
    b = Planner(pl.base, pl.market, goal, svc.cfg)
    assert a.outcome([]).achieved == b.outcome([]).achieved


def test_lena_golden_story(lena_plan):
    r = lena_plan
    assert r.baseline.p_success < 0.3                                # not on track today
    assert date(2032, 6, 1) <= r.baseline.achieved.p50 <= date(2036, 1, 1)
    assert 300 <= r.gap_baseline <= 1100                             # a gap in the hundreds per month
    assert r.plan and "use_pillar2" not in r.plan                    # plan avoids hidden retirement costs
    assert r.plan_p_success >= 0.7
    assert r.deadline.status == "ok" and r.deadline.start_by > date(2026, 9, 1)
    ranks = {c.lever_id: c.rank for c in r.levers if c.rank is not None}
    assert ranks["cancel:netflix_international"] > ranks["give_up_car"]   # Netflix is not the answer
    assert ranks["cancel:netflix_international"] > ranks["kvg_deductible"]
    assert ranks["cancel:netflix_international"] > ranks["invest_idle_cash"]


def test_kvg_break_even_around_2000(lena_plan):
    kvg = next(c for c in lena_plan.levers if c.lever_id == "kvg_deductible")
    assert kvg.details["recommended"] == 2500
    assert 1700 <= kvg.details["break_even_costs"] <= 2300
    table = {row["deductible"]: row for row in kvg.details["table"]}
    assert table[2500]["worst_case"] - table[300]["worst_case"] < 800   # bounded downside


def test_car_basket_picks_cheapest(svc):
    from mygoal.specialists.car import transit_basket
    opts = transit_basket(3000, 0, svc.cfg["prices"], 0)
    assert min(opts, key=opts.get) != "GA travelcard"      # few km: no GA
    opts = transit_basket(30000, 0, svc.cfg["prices"], 0)
    assert min(opts, key=opts.get) == "GA travelcard"      # many km: GA wins


def test_pillar2_hurts_retirement(svc):
    from mygoal.service import PlanRequest
    effects = svc.cross_goal_for("lena", PlanRequest(goal_id="home", active=["use_pillar2"]))
    retire = next(e for e in effects if e.goal_id == "retire")
    assert retire.delta_months is None or retire.delta_months >= 0
