"""Pick demo clients from the testdata with the engine: people whose first goal has a real but closable gap.

    uv run python scripts/pick_demo_clients.py [--per-tag 2] [--max-per-tag 25]

Reads <data.dir>/candidates.json (written by prep_testdata.py), runs each candidate's plan with the population risk
model and rewrites shortlist.json: per story (baby, married, separated, new job, big bill, ...) the candidates closest
to an interesting situation (on-track chance around 40%, a few years late, levers that can fix it).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict

os.environ.setdefault("MYGOAL_DATA_SOURCE", "testdata")
os.environ.setdefault("MYGOAL_DATA_DIR", "data/testdata")
os.environ.setdefault("LLM_PROVIDER", "none")

from mygoal.config import load_config, resolve_path  # noqa: E402
from mygoal.service import PlanningService, PlanRequest  # noqa: E402


def score(p: float, months_late: int | None, p_plan: float | None) -> float:
    """0 = ideal demo: about 40% on track today, 1-4 years late, and the lever plan gets it back on track."""
    late = months_late if months_late is not None else 120
    fixable = 0.0 if (p_plan or 0) >= 0.7 else 0.5
    return abs(p - 0.4) + abs(min(max(late, 0), 96) - 30) / 60 + fixable


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-tag", type=int, default=2)
    ap.add_argument("--max-per-tag", type=int, default=25)
    args = ap.parse_args()
    out_dir = resolve_path(load_config().get_path("app.data.dir"))
    candidates = json.loads((out_dir / "candidates.json").read_text(encoding="utf-8"))
    svc = PlanningService()
    by_tag: dict[str, list[dict]] = defaultdict(list)
    t0, n = time.time(), 0
    for c in candidates:
        if len(by_tag[c["tag"]]) >= args.max_per_tag:
            continue
        st = svc.state(c["id"])
        if not st.goals:
            continue
        goal = st.goals[0]
        r = svc.plan(c["id"], PlanRequest(goal_id=goal.id, include_cross_goal=False))
        b = r.baseline
        n += 1
        likely = b.achieved.p50 if b.achieved else None
        by_tag[c["tag"]].append({**c, "goal": goal.label, "p_success": round(b.p_success, 2), "months_late": b.months_late,
                                 "p_with_plan": r.plan_p_success, "likely": likely.isoformat() if likely else None,
                                 "score": round(score(b.p_success, b.months_late, r.plan_p_success), 3)})
        svc.clients.pop(c["id"], None)          # keep memory flat
        svc._planners.clear()
    picks = []
    for tag, rows in by_tag.items():
        rows.sort(key=lambda x: x["score"])
        for x in rows[: args.per_tag]:
            late = x["months_late"]
            status = "on track" if late is not None and late <= 0 else f"{x['goal']}: ~{late // 12}y {late % 12}m late" \
                if late is not None else f"{x['goal']}: out of reach"
            picks.append({**x, "story": f"{x['story']} · {status}"})
    (out_dir / "shortlist.json").write_text(json.dumps(picks, indent=1, ensure_ascii=False, default=str))
    print(f"evaluated {n} candidates in {time.time() - t0:.0f}s")
    for p in picks:
        print(f"  {p['tag']:10s} {p['name']:22s} p={p['p_success']:.2f} late={p['months_late']} plan={p['p_with_plan']} | {p['story']}")


if __name__ == "__main__":
    main()
