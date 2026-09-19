"""Reset puts a client back to the data: goals, dismissed suggestions, what-ifs and integrations."""
from mygoal.service import PlanningService


def test_reset_restores_deleted_goals_and_forgets_the_session():
    svc = PlanningService()
    before = [g.id for g in svc.state("lena").goals]
    assert before
    svc.delete_goal("lena", before[0])
    svc.partners.disconnect("lena", next(iter(svc.partners.integrations("lena")), "none"))
    assert before[0] not in [g.id for g in svc.state("lena").goals]
    assert svc.state("lena").dismissed

    svc.reset_client("lena")

    st = svc.state("lena")
    assert [g.id for g in st.goals] == before
    assert not st.dismissed and not st.custom_levers
    assert svc.partners.integrations("lena")
