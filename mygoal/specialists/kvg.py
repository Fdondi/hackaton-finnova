"""Health insurance deductible (KVG basic cover): expected cost and worst case per deductible.

cost(d, C) = 12 * premium(d) + min(C, d) + min(10% * max(C - d, 0), 700)

Past costs are only partly visible (bills paid via the insurer never touch the account), so next year's
gross cost C is sampled from a mixture shrunk toward an age-band prior: weight n / (n + 3) on the history.
"""
from __future__ import annotations

import math

import numpy as np

from ..levers import LeverContext, lever
from ..model import LeverImpact, RecurringDelta
from ..model.dist import Empirical
from ..swiss import fmt_chf, next_january


def oop(d: float, C: np.ndarray, rate: float, cap: float) -> np.ndarray:
    return np.minimum(C, d) + np.minimum(rate * np.maximum(C - d, 0), cap)


def gross_from_out_of_pocket(paid: float, d: float, rate: float, cap: float) -> float:
    if paid <= d:
        return paid
    if paid < d + cap:
        return d + (paid - d) / rate
    return d + cap / rate


@lever("kvg_deductible", origin="specialist")
def kvg_deductible(ctx: LeverContext):
    cfg, base, client = ctx.cfg, ctx.base, ctx.client
    if base.age < 19:
        return None
    k = cfg["kvg"]
    rate, cap = k["copay_rate"], k["copay_cap_adult"]
    quotes = ctx.services.get("insurer_quotes")
    a = ctx.book("kvg_deductible")
    current_d = int(a.get("current_deductible", client.health.deductible or 300, label="Your deductible today", unit="CHF",
                          source="client_data" if client.health.deductible else "market_default",
                          needs_confirmation=not client.health.deductible, editable=False))
    prem_tx = sum(-r.monthly_equivalent for r in ctx.profile.recurring if r.active and r.category == "health_premium")
    premium_now = a.get("premium_monthly", prem_tx or client.health.premium_monthly or 400, label="Premium per month today",
                        unit="CHF/month", source="transactions" if prem_tx else "client_data", step=5)
    model = client.health.model or "standard"
    adults = max(1, client.household.adults)
    q_now = quotes.quote(age=base.age, canton=client.canton, deductible=current_d, model=model)
    # the discount is per adult; the household premium may also include children
    premium = {d: premium_now + adults * (quotes.quote(age=base.age, canton=client.canton, deductible=d, model=model) - q_now)
               for d in k["deductibles_adult"]}

    paid = max(0.0, ctx.profile.monthly("health_costs") * 12)
    seen = gross_from_out_of_pocket(paid, current_d, rate, cap)
    prior = cfg.by_age("kvg.cost_model.age_bands", int(base.age))
    c_hist = a.get("medical_costs", round(seen, -1), label="Medical costs per year billed to basic insurance (all adults)", unit="CHF/yr",
                   source="transactions", low=0, high=max(6000, 3 * seen), step=100, needs_confirmation=True,
                   note="Partially visible: bills the insurer pays directly never show up in the account")
    n = min(ctx.profile.history_months / 12, 5)
    w = n / (n + cfg["kvg"]["cost_model"]["prior_weight_years"])
    p_zero = w * (0.5 if c_hist < 50 else 0.02) + (1 - w) * prior["p_zero"]
    median = math.exp(w * math.log(max(c_hist, 100)) + (1 - w) * math.log(prior["median_positive"]))
    rng = np.random.default_rng(7)
    C = np.where(rng.uniform(size=(adults, 4000)) < p_zero, 0.0,
                 median / adults * np.exp(prior["sigma"] * rng.standard_normal((adults, 4000))))

    cost = {d: 12 * premium[d] + oop(d, C, rate, cap).sum(axis=0) for d in premium}
    expected = {d: float(v.mean()) for d, v in cost.items()}
    worst = {d: 12 * premium[d] + adults * (d + cap) for d in premium}
    free_cash = base.cash - base.buffer_reserve
    affordable = [d for d in premium if adults * (d + cap) <= free_cash] or [current_d]
    best = min(affordable, key=lambda d: expected[d])
    saving = expected[current_d] - expected[best]
    if best == current_d or saving < 100:
        return None
    deltas = (cost[current_d] - cost[best]) / 12
    start = next_january(ctx.start)
    table = [{"deductible": d, "premium_year": round(12 * premium[d]), "expected_cost": round(expected[d]),
              "worst_case": round(worst[d]), "p90_cost": round(float(np.percentile(cost[d], 90)))} for d in sorted(premium)]
    return LeverImpact(
        lever_id="kvg_deductible", title=f"Raise your health deductible to {best:,}".replace(",", "'"),
        description=(f"Premiums drop by {fmt_chf(12 * (premium[current_d] - premium[best]))}/year. With your usual medical costs "
                     f"you keep about {fmt_chf(saving)} a year."),
        group="no_lifestyle_cost", effort="low", confidence="estimated", product_trigger="health_insurance", icon="heart-pulse",
        recurring=[RecurringDelta(start=start, monthly=Empirical(samples=deltas[:1000].round(2).tolist()), resample="yearly",
                                  label="Lower premium minus extra out-of-pocket")],
        side_effects=[f"In a bad health year up to {fmt_chf(worst[best] - worst[current_d])} more than today",
                      "Tell your insurer by 31 Dec (switching insurer: by 30 Nov)"],
        headline_monthly=round(saving / 12),
        details={"table": table, "current": current_d, "recommended": best, "title_args": {"deductible": f"{best:,}".replace(",", "'")},
                 "break_even_costs": _break_even(premium, current_d, best, rate, cap, adults),
                 "quote_source": getattr(quotes, "source", "insurer service")},
        assumptions=a.list(),
    )


def _break_even(premium: dict, d0: int, d1: int, rate: float, cap: float, adults: int = 1) -> int:
    """Yearly medical costs per adult above which the higher deductible stops paying off."""
    C = np.arange(0, 10000, 10.0)
    diff = (12 * premium[d1] + adults * oop(d1, C, rate, cap)) - (12 * premium[d0] + adults * oop(d0, C, rate, cap))
    above = np.nonzero(diff > 0)[0]
    return int(C[above[0]]) if len(above) else 10000
