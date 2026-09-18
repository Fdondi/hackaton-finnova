"""Application service: the one place that orchestrates adapter -> profile -> engine -> levers -> texts.

The FastAPI app, the Streamlit debug page and tests all call this, so swapping the web framework
(or adding a CLI, a batch job for the advisor "triggers" list, ...) never touches the domain code.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .adapters import get_source
from .categorise import load_taxonomy
from .config import Config, load_config
from .engine import Baseline, build_baseline, build_market
from .engine.solve import Deadline, GoalOutcome, Planner, apply_goal_changes
from .explain import DriverInput, chf, month, strings, t, top_drivers
from .goals import GOALS, parse_params, target_date
from .levers import LeverContext, build_levers, build_primitive, combine
from .model import Assumption, AssumptionBook, Dataset, GoalSpec, LeverImpact, months_between
from .profile import Profile, build_profile
from .registry import load_plugins
from .services import build_services


# ---------------------------------------------------------------- API models
class PlanRequest(BaseModel):
    goal_id: str
    active: list[str] = Field(default_factory=list)
    overrides: dict[str, dict[str, float]] = Field(default_factory=dict)   # "global" or lever_id -> key -> value
    lang: str = "en"
    n_paths: int | None = None
    include_cross_goal: bool = True


class AssumptionView(Assumption):
    source_label: str = ""


class LeverCard(BaseModel):
    lever_id: str
    title: str
    description: str
    group: str
    effort: str
    confidence: str
    side_effects: list[str]
    product_trigger: str | None
    icon: str | None
    origin: str
    details: dict[str, Any]
    assumptions: list[AssumptionView]
    months_gained: int | None = None
    delta_p: float = 0.0
    monthly_equivalent: float = 0.0
    impact_label: str = ""
    active: bool = False
    in_plan: bool = False
    helps: bool = True
    trade_off: bool = False
    rank: int | None = None


class CrossGoalEffect(BaseModel):
    source_goal_id: str
    goal_id: str
    label: str
    from_label: str
    to_label: str
    delta_months: int | None
    text: str


class PlanResponse(BaseModel):
    client_id: str
    goal: GoalSpec
    baseline: GoalOutcome
    scenario: GoalOutcome
    gap_baseline: float | None
    gap_scenario: float | None
    plan: list[str]
    plan_p_success: float | None
    deadline: Deadline
    deadline_for: Literal["active", "plan"]
    levers: list[LeverCard]
    cross_goal: list[CrossGoalEffect]
    drivers: list[str]
    texts: dict[str, str]
    assumptions: list[AssumptionView]
    timing_ms: dict[str, int]


class CustomLever(BaseModel):
    lever_id: str
    title: str
    parts: list[dict[str, Any]]            # [{"primitive": name, "params": {...}}]
    created_by: str = "agent"
    group: str = "structural"
    effort: str = "medium"
    note: str | None = None


# ---------------------------------------------------------------- workspace
@dataclass
class ClientState:
    ds: Dataset
    profile: Profile
    goals: list[GoalSpec]
    custom_levers: dict[str, CustomLever] = field(default_factory=dict)
    version: int = 0
    risk: Any = None                       # population.RiskProfile when the bank's population data is available
    notes: list[dict[str, str]] = field(default_factory=list)   # life facts the client told us (facts page)
    ai_suggested: bool = False             # the LLM already proposed goals for this client
    ai_facts: dict[str, Any] = field(default_factory=dict)      # cached LLM reading of the data, per language
    lock: Any = field(default_factory=threading.Lock)            # one LLM job per client at a time (pages call twice)


def _h(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


class PlanningService:
    def __init__(self, cfg: Config | None = None):
        load_plugins()
        self.cfg = cfg or load_config()
        self.source = get_source(self.cfg)
        self.services = build_services(self.cfg)
        self.clients: dict[str, ClientState] = {}
        self._planners: OrderedDict[str, Planner] = OrderedDict()
        self._rankings: dict[str, tuple] = {}

    # ---- clients ----
    def list_clients(self):
        return self.source.list_clients()

    def state(self, client_id: str) -> ClientState:
        if client_id not in self.clients:
            ds = self.source.load(client_id)
            profile = build_profile(ds, self.cfg)
            pop = self.services.get("population")
            risk = pop.risk_for(ds, profile) if pop is not None else None
            self.clients[client_id] = ClientState(ds=ds, profile=profile, goals=list(ds.client.goals), risk=risk)
        return self.clients[client_id]

    def upsert_goal(self, client_id: str, goal: GoalSpec) -> list[GoalSpec]:
        st = self.state(client_id)
        GOALS.get(goal.type)  # validates the type
        parse_params(GOALS.get(goal.type), goal)
        ids = [g.id for g in st.goals]
        st.goals = [goal if g.id == goal.id else g for g in st.goals] if goal.id in ids else [*st.goals, goal]
        st.version += 1
        return st.goals

    def delete_goal(self, client_id: str, goal_id: str) -> list[GoalSpec]:
        st = self.state(client_id)
        st.goals = [g for g in st.goals if g.id != goal_id]
        st.version += 1
        return st.goals

    def add_custom_lever(self, client_id: str, lever: CustomLever) -> CustomLever:
        st = self.state(client_id)
        st.custom_levers[lever.lever_id] = lever
        st.version += 1
        return lever

    def remove_custom_lever(self, client_id: str, lever_id: str) -> None:
        st = self.state(client_id)
        st.custom_levers.pop(lever_id, None)
        st.version += 1

    def goal(self, client_id: str, goal_id: str) -> GoalSpec:
        for g in self.state(client_id).goals:
            if g.id == goal_id:
                return g
        raise KeyError(f"unknown goal {goal_id}")

    # ---- building blocks ----
    def baseline(self, client_id: str, global_overrides: dict[str, float] | None = None):
        st = self.state(client_id)
        book = AssumptionBook(global_overrides)
        base = build_baseline(st.profile, st.ds.client, self.cfg, book, risk=st.risk)
        market = build_market(self.cfg, book, risk=st.risk)
        return base, market, book.list()

    def planner(self, client_id: str, goal: GoalSpec, global_overrides: dict | None, n_paths: int | None = None) -> Planner:
        key = _h([client_id, goal.model_dump(), global_overrides or {}, n_paths])
        if key in self._planners:
            self._planners.move_to_end(key)
            return self._planners[key]
        base, market, _ = self.baseline(client_id, global_overrides)
        pl = Planner(base, market, goal, self.cfg, n_paths=n_paths)
        self._planners[key] = pl
        while len(self._planners) > 48:
            self._planners.popitem(last=False)
        return pl

    def lever_context(self, client_id: str, goal: GoalSpec, base: Baseline, overrides: dict) -> LeverContext:
        st = self.state(client_id)
        return LeverContext(client=st.ds.client, profile=st.profile, base=base, goal=goal, cfg=self.cfg,
                            overrides={k: v for k, v in overrides.items() if k != "global"}, services=self.services,
                            target=target_date(GOALS.get(goal.type), goal, base))

    def levers(self, client_id: str, goal: GoalSpec, base: Baseline, overrides: dict) -> list[LeverImpact]:
        st = self.state(client_id)
        ctx = self.lever_context(client_id, goal, base, overrides)
        out = build_levers(ctx)
        for cl in st.custom_levers.values():
            try:
                out.append(self.build_custom(cl, ctx))
            except Exception as exc:  # a broken agent lever must not break the page
                st.ds.client.extra.setdefault("lever_errors", []).append(f"{cl.lever_id}: {exc}")
        return out

    @staticmethod
    def build_custom(cl: CustomLever, ctx: LeverContext) -> LeverImpact:
        parts = [build_primitive(p["primitive"], p["params"], ctx, cl.lever_id, key_prefix=f"{i}." if len(cl.parts) > 1 else "")
                 for i, p in enumerate(cl.parts)]
        lever = parts[0] if len(parts) == 1 else combine(cl.lever_id, cl.title, parts)
        lever.title, lever.origin = cl.title, "agent"
        lever.group, lever.effort = cl.group, cl.effort
        if cl.note:
            lever.description = cl.note
        return lever

    # ---- main question ----
    def plan(self, client_id: str, req: PlanRequest) -> PlanResponse:
        timing: dict[str, int] = {}
        t0 = time.perf_counter()

        def tick(name: str):
            nonlocal t0
            now = time.perf_counter()
            timing[name] = int((now - t0) * 1000)
            t0 = now

        st = self.state(client_id)
        lang = req.lang
        goal = self.goal(client_id, req.goal_id)
        glob = req.overrides.get("global", {})
        pl = self.planner(client_id, goal, glob, req.n_paths)
        base = pl.base
        _, _, global_assumptions = self.baseline(client_id, glob)
        all_levers = self.levers(client_id, goal, base, req.overrides)
        by_id = {lv.lever_id: lv for lv in all_levers}
        active = [by_id[i] for i in req.active if i in by_id]
        options = [lv for lv in all_levers if lv.group != "life_event"]
        tick("setup")

        baseline = self.worst_case_texts(pl.outcome([], fan=True), lang)
        scenario = self.worst_case_texts(pl.outcome(active, fan=True), lang) if active else baseline
        tick("outcomes")

        planning = self.cfg["app"]["planning"]
        rank_key = _h([client_id, goal.model_dump(), req.overrides, st.version, req.n_paths])
        if rank_key not in self._rankings:
            scores = pl.rank(options)
            excluded_groups = set(planning.get("auto_plan_excluded_groups", []))
            excluded = set(planning.get("auto_plan_excluded_levers", []))
            candidates = [lv for lv in options if lv.group not in excluded_groups and lv.lever_id not in excluded]
            plan_ids = pl.auto_plan(candidates, planning["effort_weight"],
                                    weight_multiplier=planning.get("auto_plan_weight_multiplier"))
            self._rankings[rank_key] = (scores, plan_ids)
        scores, plan_ids = self._rankings[rank_key]
        tick("ranking")

        gap_baseline = pl.gap_monthly([])
        gap_scenario = pl.gap_monthly(active) if active else gap_baseline
        plan_levers = [by_id[i] for i in plan_ids if i in by_id]
        plan_p = pl.p_success(plan_levers) if plan_levers else None
        active_options = [lv for lv in active if lv.group not in ("life_event", "goal_change")]
        life_events = [lv for lv in active if lv.group == "life_event"]
        if active_options:
            deadline, deadline_for = pl.deadline(active_options, fixed_impacts=life_events), "active"
        else:
            deadline, deadline_for = pl.deadline(plan_levers, fixed_impacts=life_events), "plan"
        tick("gap_deadline")

        cross = self.cross_goal(client_id, goal, active, scenario, glob, lang, req.n_paths) if req.include_cross_goal else []
        tick("cross_goal")

        cards = self.cards(all_levers, scores, set(req.active), set(plan_ids), lang,
                           set(planning.get("auto_plan_excluded_levers", [])))
        drivers = [d.text for d in top_drivers(DriverInput(goal=apply_goal_changes(goal, active), outcome=scenario, profile=st.profile,
                                                            base=base, lang=lang))]
        texts = self.goal_texts(goal, baseline, scenario, gap_baseline, gap_scenario, deadline, plan_levers, lang,
                                months_between(base.start, scenario.target_date), base)
        tick("texts")
        return PlanResponse(
            client_id=client_id, goal=goal, baseline=baseline, scenario=scenario, gap_baseline=gap_baseline,
            gap_scenario=gap_scenario, plan=plan_ids, plan_p_success=plan_p, deadline=deadline, deadline_for=deadline_for,
            levers=cards, cross_goal=cross, drivers=drivers, texts=texts,
            assumptions=[self.view(a, lang) for a in global_assumptions], timing_ms=timing,
        )

    # ---- pieces ----
    @staticmethod
    def _worst_case_sentence(seg, lang: str) -> str:
        weak_market = seg.market_shortfall >= 0.08
        if seg.job_loss_months and weak_market:
            return t("worst_case.job_and_market", lang, months=seg.job_loss_months, start=month(seg.job_loss_start, lang),
                     shortfall=f"{seg.market_shortfall:.0%}")
        if seg.job_loss_months:
            return t("worst_case.job_only", lang, months=seg.job_loss_months, start=month(seg.job_loss_start, lang))
        if weak_market:
            return t("worst_case.market_only", lang, shortfall=f"{seg.market_shortfall:.0%}")
        return t("worst_case.generic", lang)

    def worst_case_texts(self, outcome: GoalOutcome, lang: str) -> GoalOutcome:
        """A copy of `outcome` with each fan-chart worst-case segment's localized sentence filled in.

        Doesn't mutate `outcome` itself: it (and its `.fan`) come straight out of the planner's cache,
        shared across requests (and languages) for the same impacts, and concurrent requests can run
        in different worker threads.
        """
        if not outcome.fan:
            return outcome
        segs = [seg.model_copy(update={"text": self._worst_case_sentence(seg, lang)}) for seg in outcome.fan.worst_case]
        return outcome.model_copy(update={"fan": outcome.fan.model_copy(update={"worst_case": segs})})

    def view(self, a: Assumption, lang: str) -> AssumptionView:
        return AssumptionView(**a.model_dump(), source_label=t(f"sources.{a.source}", lang))

    def cards(self, levers: list[LeverImpact], scores, active: set[str], plan: set[str], lang: str,
              trade_offs: set[str]) -> list[LeverCard]:
        score_by = {s.lever_id: (i, s) for i, s in enumerate(scores)}
        cards = []
        for lv in levers:
            rank, s = score_by.get(lv.lever_id, (None, None))
            months = s.months_gained if s else None
            if months and months > 0:
                label = t("lever.month_gained_one" if months == 1 else "lever.months_gained", lang, months=months)
            elif months and months < 0:
                label = t("lever.month_lost_one" if months == -1 else "lever.months_lost", lang, months=-months)
            elif s and s.delta_p > 0.005:
                label = t("lever.more_futures", lang, n=round(100 * s.delta_p))
            else:
                label = t("lever.no_effect", lang) if s else ""
            cards.append(LeverCard(
                lever_id=lv.lever_id,
                title=t(f"lever_titles.{lv.details.get('title_key', lv.lever_id.split(':')[0])}", lang, default=lv.title,
                        **lv.details.get("title_args", {})),
                description=lv.description, group=lv.group, effort=lv.effort, confidence=lv.confidence,
                side_effects=lv.side_effects, product_trigger=lv.product_trigger, icon=lv.icon, origin=lv.origin,
                details=lv.details, assumptions=[self.view(a, lang) for a in lv.assumptions],
                months_gained=months, delta_p=s.delta_p if s else 0.0,
                monthly_equivalent=s.monthly_equivalent if s else (lv.headline_monthly or 0.0),
                impact_label=label, active=lv.lever_id in active, in_plan=lv.lever_id in plan,
                helps=bool(s and ((s.months_gained or 0) > 0 or s.delta_p > 0.005)) if s else True,
                trade_off=lv.lever_id in trade_offs, rank=rank,
            ))
        return cards

    def goal_texts(self, goal: GoalSpec, base: GoalOutcome, scen: GoalOutcome, gap_b, gap_s, deadline: Deadline,
                   plan: list[LeverImpact], lang: str, months_to_target: int | None = None,
                   base_line: Baseline | None = None) -> dict[str, str]:
        def when(d):
            if goal.type == "retirement" and d is not None and base_line is not None:
                return f"{t('cross_goal.age', lang, age=f'{base_line.age_at(d):.0f}')} ({month(d, lang)})"
            return month(d, lang)

        def headline(o: GoalOutcome) -> str:
            kw = dict(label=goal.label, target=when(o.target_date), p50=when(o.achieved.p50),
                      n=o.futures_of_10, horizon=month(o.achieved.horizon_end, lang))
            if o.p_success >= 0.7 and o.achieved.p90 is not None and o.achieved.p90 <= o.start:
                return t("goal.ready", lang, **kw)
            if o.p_success >= 0.7:
                return t("goal.on_track", lang, **kw)
            if o.achieved.p50 is None:
                return t("goal.never", lang, **kw)
            return t("goal.late", lang, **kw)

        def gap_text(g):
            if g is None:
                return t("goal.gap_unreachable", lang)
            if g <= 0:
                return t("goal.gap_none", lang)
            return t("goal.gap", lang, gap=chf(g))

        tgt = month(scen.target_date, lang)
        if deadline.status == "on_track":
            dl = t("goal.deadline_on_track", lang)
        elif deadline.status == "not_enough":
            dl = t("goal.deadline_not_enough", lang, target=tgt)
        elif deadline.months_of_slack == 0:
            dl = t("goal.deadline_now", lang, target=tgt)
        elif months_to_target is not None and deadline.months_of_slack >= months_to_target:
            dl = t("goal.deadline_any_time", lang, target=tgt)
        else:
            dl = t("goal.deadline_ok", lang, start_by=month(deadline.start_by, lang), target=tgt)
        return {
            "headline": headline(base), "headline_scenario": headline(scen),
            "futures": t("goal.futures", lang, n=scen.futures_of_10, target=tgt),
            "range": t("goal.range", lang, p10=month(scen.achieved.p10, lang), p90=month(scen.achieved.p90, lang))
            if scen.achieved.p90 and scen.achieved.p10 != scen.achieved.p90 else "",
            "gap": gap_text(gap_b), "gap_scenario": gap_text(gap_s), "deadline": dl,
            "plan": t("goal.plan", lang, levers=" + ".join(lv.title for lv in plan)) if plan else "",
        }

    def cross_goal_for(self, client_id: str, req: PlanRequest) -> list[CrossGoalEffect]:
        goal = self.goal(client_id, req.goal_id)
        glob = req.overrides.get("global", {})
        pl = self.planner(client_id, goal, glob, req.n_paths)
        by_id = {lv.lever_id: lv for lv in self.levers(client_id, goal, pl.base, req.overrides)}
        active = [by_id[i] for i in req.active if i in by_id]
        return self.cross_goal(client_id, goal, active, pl.outcome(active), glob, req.lang, req.n_paths)

    def _when_label(self, goal: GoalSpec, o: GoalOutcome, base: Baseline, lang: str) -> str:
        if o.achieved.p50 is None:
            return t("cross_goal.never", lang, horizon=month(o.achieved.horizon_end, lang))
        if goal.type == "retirement":
            return f"{t('cross_goal.age', lang, age=f'{base.age_at(o.achieved.p50):.0f}')} ({month(o.achieved.p50, lang)})"
        return month(o.achieved.p50, lang)

    def cross_goal(self, client_id: str, goal: GoalSpec, active: list[LeverImpact], scenario: GoalOutcome,
                   glob: dict, lang: str, n_paths: int | None) -> list[CrossGoalEffect]:
        """How achieving this goal (with the chosen options) moves the client's other goals, and vice versa."""
        st = self.state(client_id)
        out: list[CrossGoalEffect] = []
        neutral = [lv.model_copy(update={"goal_changes": []}) for lv in active]
        spec = apply_goal_changes(goal, active)
        when = scenario.target_date if scenario.p_success >= 0.7 else scenario.achieved.p50
        plugin = GOALS.get(goal.type)
        for other in st.goals:
            if other.id == goal.id or other.status != "confirmed":
                continue
            opl = self.planner(client_id, other, glob, n_paths)
            other_base = opl.outcome([])
            if when is not None and (other_base.achieved.p50 is None or when <= other_base.achieved.p50):
                commit = plugin.commitment(spec, parse_params(plugin, spec), opl.base, self.cfg, when)
                if commit is not None:
                    before, after = opl.outcome(neutral), opl.outcome(neutral + [commit])
                    out.append(self._effect(goal, other, when, before, after, opl.base, lang))
            # the other goal, reached at its target date, may push this one back
            other_plugin = GOALS.get(other.type)
            other_when = target_date(other_plugin, other, opl.base)
            if scenario.achieved.p50 and other_when < scenario.achieved.p50 and other.type != "retirement":
                pl = self.planner(client_id, goal, glob, n_paths)
                commit = other_plugin.commitment(other, parse_params(other_plugin, other), pl.base, self.cfg, other_when)
                if commit is not None:
                    out.append(self._effect(other, goal, other_when, scenario, pl.outcome(active + [commit]), pl.base, lang))
        return out

    def _effect(self, source: GoalSpec, target: GoalSpec, when: date, before: GoalOutcome, after: GoalOutcome,
                base: Baseline, lang: str) -> CrossGoalEffect:
        fl, tl = self._when_label(target, before, base, lang), self._when_label(target, after, base, lang)
        delta = months_between(before.achieved.p50, after.achieved.p50) if before.achieved.p50 and after.achieved.p50 else None
        text = t("cross_goal.no_change", lang, source=source.label, other=target.label) if fl == tl or delta == 0 else \
            t("cross_goal.shift", lang, source=source.label, when=month(when, lang), other=target.label, from_=fl, to=tl)
        return CrossGoalEffect(source_goal_id=source.id, goal_id=target.id, label=target.label, from_label=fl, to_label=tl,
                               delta_months=delta, text=text)

    # ---- what-ifs ----
    @property
    def whatif(self):
        if not hasattr(self, "_whatif"):
            from .agent import WhatIfEngine
            self._whatif = WhatIfEngine(self)
        return self._whatif

    def evaluate_lever(self, client_id: str, goal_id: str, lever_id: str, overrides: dict | None = None) -> dict[str, Any]:
        """Effect of one lever on one goal, on its own."""
        overrides = overrides or {}
        goal = self.goal(client_id, goal_id)
        pl = self.planner(client_id, goal, overrides.get("global", {}))
        lever = next(lv for lv in self.levers(client_id, goal, pl.base, overrides) if lv.lever_id == lever_id)
        score = pl.rank([lever])[0]
        return {"lever_id": lever_id, "title": lever.title, "months_gained": score.months_gained, "delta_p": score.delta_p,
                "p_success": score.p_success, "achieved_p50": score.achieved_p50, "monthly_equivalent": score.monthly_equivalent,
                "assumptions": [a.model_dump() for a in lever.assumptions]}

    # ---- overview ("where you stand") ----
    def bookings(self, client_id: str, lang: str = "en") -> list[dict[str, Any]]:
        st = self.state(client_id)
        tax = load_taxonomy()
        return [{
            "id": b.id, "date": b.booking_date, "amount": b.amount, "merchant": b.merchant or b.counterparty or b.text,
            "category": b.category, "category_label": tax.label(b.category, lang) if b.category else None,
            "tags": b.tags, "text": b.text,
        } for b in sorted(st.ds.bookings, key=lambda b: b.booking_date, reverse=True)]

    def overview(self, client_id: str, lang: str = "en") -> dict[str, Any]:
        st = self.state(client_id)
        p = st.profile
        tax = load_taxonomy()
        base, market, _ = self.baseline(client_id)
        goals, breach = [], None
        for g in st.goals:
            if g.status != "confirmed":           # suggestions aren't simulated until the client confirms them
                goals.append({**g.model_dump(mode="json"), "status_info": None})
                continue
            pl = self.planner(client_id, g, {}, None)
            o = pl.outcome([])
            breach = o.p_buffer_breach if breach is None else breach
            goals.append({**g.model_dump(mode="json"), "status_info": {
                "p_success": o.p_success, "futures_of_10": o.futures_of_10, "p50": o.achieved.p50,
                "target_date": o.target_date,
                "headline": self.goal_texts(g, o, o, None, None, Deadline(status="ok"), [], lang, base_line=pl.base)["headline"]}})
        fcf = p.free_cash_flow_monthly
        trend_key = {"up": "stand.trend_up", "down": "stand.trend_down", "flat": "stand.trend_flat"}[p.trend.direction]
        return {
            "client": {"id": st.ds.client.id, "name": st.ds.client.name, "age": p.age, "canton": st.ds.client.canton,
                       "household": st.ds.client.household.model_dump()},
            "as_of": p.as_of,
            "stand": {
                "income_monthly": round(p.income.salary_net_monthly_avg + p.income.other_income_monthly),
                "spending_monthly": round(p.spending_monthly), "fcf_monthly": round(fcf), "savings_rate": p.savings_rate,
                "buffer_months": p.buffer_months, "trend": p.trend.model_dump(), "opaque_monthly": round(p.opaque_monthly),
                "opaque_share": p.opaque_share, "opaque_breakdown": p.opaque_breakdown,
                "liquid": round(p.balances.liquid), "invested": round(p.balances.invested), "p3a": round(p.balances.p3a),
                "p2": round(p.balances.p2), "gross_income": round(p.income.gross_annual),
            },
            "texts": {
                "fcf": t("stand.fcf" if fcf >= 0 else "stand.fcf_negative", lang, fcf=chf(abs(fcf))),
                "buffer": t("stand.buffer", lang, months=f"{p.buffer_months:.0f}"),
                "trend": t(trend_key, lang, change=chf(abs(p.trend.change))),
                "opaque": t("stand.opaque", lang, amount=chf(p.opaque_monthly)),
            },
            "spending": [{"category": f.category, "label": tax.label(f.category, lang), "monthly": round(f.monthly),
                          "fixed": round(f.fixed_monthly), "variable": round(f.variable_monthly), "opaque": f.opaque,
                          "top_merchants": [m.model_dump() for m in f.top_merchants[:3]]}
                         for f in p.flows if f.kind == "spending" and f.monthly > 0],
            "hints": [h.model_dump() for h in p.hints],
            "goals": goals,
            "goal_types": sorted(GOALS),
            "data_quality": [n.model_dump() for n in p.data_quality],
            "recurring": [r.model_dump() for r in p.recurring if r.active],
            "risk": self.risk_view(client_id, breach, market.job_loss_prob, lang),
        }

    def risk_view(self, client_id: str, breach: float | None, job_prob: float, lang: str = "en") -> dict[str, Any] | None:
        """Surprise bills and income risk measured on people like this client (population data), in plain words."""
        st = self.state(client_id)
        r, p = st.risk, st.profile
        if r is None:
            return None
        rs = strings(lang).get("risk", {})
        names = rs.get("cause_names") or {}
        causes = [names.get(c["vendor"], c["vendor"]) for c in r.top_causes]
        if r.segment == "all":
            segment = rs.get("everyone", "everyone in the data")
        else:
            band, emp = r.segment.split("|")
            segment = t("risk.segment", lang, who=(rs.get("who") or {}).get(emp, emp), band=band.replace("-", "–"))
        bad_year = r.year_total(0.9)
        monthly_saving = max(p.free_cash_flow_monthly, 0.0)          # same figure as the "left each month" tile
        cushion = max(p.balances.liquid, 0.0)
        refill = bad_year / monthly_saving if monthly_saving > 0 else None
        texts = [
            t("risk.bills", lang, segment=segment, n=f"{r.n_people:,}".replace(",", "'"), rate=f"{r.segment_rate:.1f}",
              threshold=chf(r.bill_threshold), p50=chf(r.bill_p50 or 0)),
            t("risk.causes", lang, causes=", ".join(causes)),
            t("risk.yours", lang, n=r.personal_bills, rate=f"{r.bill_rate:.1f}"),
            t("risk.bad_year", lang, amount=chf(bad_year)),
            t("risk.cushion", lang, times=f"{cushion / bad_year:.0f}") if bad_year and cushion >= bad_year
            else t("risk.cushion_short", lang, liquid=chf(cushion)),
            t("risk.recover", lang, months=f"{refill:.0f}") if refill is not None and refill <= 36 else t("risk.recover_long", lang),
            t("risk.job_population" if r.salary_gap_prob is not None else "risk.job_default", lang,
              prob=f"{job_prob:.1%}", months=f"{r.salary_gap_months or 0:.0f}"),
            t("risk.in_plan", lang) + " " + (t("risk.breach", lang, n=round(breach * 10)) if breach and breach >= 0.05
                                             else t("risk.breach_rare", lang)),
        ]
        return {"segment": r.segment, "segment_label": segment, "n_people": r.n_people, "bill_rate": r.bill_rate,
                "bill_threshold": r.bill_threshold, "bill_p50": r.bill_p50, "bill_p90": r.bill_p90, "bad_year": round(bad_year),
                "personal_bills": r.personal_bills, "causes": causes, "cushion": round(cushion),
                "cushion_times": round(cushion / bad_year, 1) if bad_year else None, "p_breach": breach,
                "job_prob": job_prob, "job_source": "population" if r.salary_gap_prob is not None else "market_default",
                "texts": texts}

    def i18n(self, lang: str) -> dict:
        return strings(lang)
