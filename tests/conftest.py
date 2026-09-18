import os

import pytest

os.environ.setdefault("LLM_PROVIDER", "none")   # tests never call a model


@pytest.fixture(scope="session")
def svc():
    from mygoal.service import PlanningService
    return PlanningService()


@pytest.fixture(scope="session")
def lena_plan(svc):
    from mygoal.service import PlanRequest
    return svc.plan("lena", PlanRequest(goal_id="home", include_cross_goal=False))
