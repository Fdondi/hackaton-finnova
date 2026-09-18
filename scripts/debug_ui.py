"""Streamlit debug page over the same PlanningService: no frontend skills needed, and a fallback demo.

    uv run --extra debug-ui streamlit run scripts/debug_ui.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from mygoal.service import PlanningService, PlanRequest

st.set_page_config(page_title="My Goal, My Plan (debug)", layout="wide")


@st.cache_resource
def service() -> PlanningService:
    return PlanningService()


svc = service()
with st.sidebar:
    clients = svc.list_clients()
    client_id = st.selectbox("Client", [c.id for c in clients], format_func=lambda i: next(c.name for c in clients if c.id == i))
    lang = st.radio("Language", ["en", "de"], horizontal=True)
    state = svc.state(client_id)
    goal_id = st.selectbox("Goal", [g.id for g in state.goals], format_func=lambda i: svc.goal(client_id, i).label)
    n_paths = st.select_slider("Paths", [250, 500, 1000, 2000], value=1000)

profile = state.profile
tab_plan, tab_profile, tab_whatif, tab_data = st.tabs(["Plan", "Profile", "What-if", "Bookings"])

with tab_plan:
    base_plan = svc.plan(client_id, PlanRequest(goal_id=goal_id, lang=lang, n_paths=n_paths, include_cross_goal=False))
    options = {c.lever_id: c.title for c in base_plan.levers}
    active = st.multiselect("Active levers", list(options), default=[], format_func=options.get)
    with st.expander("Global assumptions"):
        overrides = {}
        for a in base_plan.assumptions:
            if a.editable:
                v = st.number_input(f"{a.label} [{a.unit}] ({a.source})", value=float(a.value), key=f"g-{a.key}")
                if abs(v - a.value) > 1e-9:
                    overrides[a.key] = v
    plan = svc.plan(client_id, PlanRequest(goal_id=goal_id, active=active, lang=lang, n_paths=n_paths,
                                           overrides={"global": overrides}))
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("P(success)", f"{plan.scenario.p_success:.0%}", f"{plan.scenario.p_success - plan.baseline.p_success:+.0%}")
    c2.metric("Median date", str(plan.scenario.achieved.p50))
    c3.metric("Gap / month", plan.texts["gap_scenario"])
    c4.metric("Deadline", str(plan.deadline.start_by or plan.deadline.status))
    st.write(plan.texts)
    st.write({"drivers": plan.drivers, "cross_goal": [x.text for x in plan.cross_goal], "timing_ms": plan.timing_ms})
    fan = plan.scenario.fan
    if fan:
        st.line_chart(pd.DataFrame({"p10": fan.p10, "p50": fan.p50, "p90": fan.p90, "need": fan.need}, index=pd.to_datetime(fan.dates)))
    st.dataframe(pd.DataFrame([{k: getattr(c, k) for k in ("rank", "lever_id", "title", "group", "impact_label", "monthly_equivalent",
                                                            "delta_p", "effort", "confidence", "in_plan", "helps")} for c in plan.levers]))

with tab_profile:
    st.json({"income": profile.income.model_dump(), "balances": profile.balances.model_dump(), "fcf": profile.free_cash_flow_monthly,
             "buffer_months": profile.buffer_months, "opaque": profile.opaque_breakdown,
             "notes": [n.message for n in profile.data_quality]})
    st.dataframe(pd.DataFrame([f.model_dump(exclude={"top_merchants"}) for f in profile.flows]))
    st.dataframe(pd.DataFrame([r.model_dump() for r in profile.recurring]))
    st.dataframe(pd.DataFrame([h.model_dump() for h in profile.hints]))

with tab_whatif:
    text = st.text_input("What if…", "What if I sell my Warhammer collection?")
    if st.button("Run") and text:
        st.session_state["whatif"] = svc.whatif.start(client_id, goal_id, text, lang)
    result = st.session_state.get("whatif")
    if result:
        st.json(result.model_dump(mode="json"))
        if result.status == "question":
            answer = st.text_input(result.question.text, str(result.question.default or ""))
            if st.button("Answer"):
                st.session_state["whatif"] = svc.whatif.answer(result.session_id, answer)
                st.rerun()

with tab_data:
    df = pd.DataFrame([b.model_dump(exclude={"extra"}) for b in state.ds.bookings])
    cat = st.multiselect("Category", sorted(df["category"].dropna().unique()))
    st.dataframe(df[df["category"].isin(cat)] if cat else df, height=600)
