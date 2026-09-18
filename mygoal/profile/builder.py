"""Profile builder: canonical bookings -> where the client stands today.

Averages use the last 12 complete months, skipping months missing from the export. Recurring bills
use their current amount (rent went up? we project the new rent). Variable spending uses the mean,
not the median: travel happens twice a year and a median would pretend it doesn't exist.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from ..categorise import Categoriser, load_taxonomy
from ..config import Config
from ..model import AssumptionBook, Dataset, add_months, month_start
from ..model.dates import ym
from ..registry import load_plugins
from .hints import HINT_DETECTORS, HintContext
from .model import (
    Balances, CategoryFlow, DataNote, IncomeProfile, MerchantTotal, Profile, Trend,
)
from .recurring import detect_recurring

LIQUID_TYPES = {"private", "savings", "card"}


def _frame(ds: Dataset) -> pd.DataFrame:
    rows = [{
        "id": b.id, "account_id": b.account_id, "booking_date": b.booking_date, "amount": b.amount,
        "merchant": b.merchant or "unknown", "category": b.category or "unexplained", "tags": list(b.tags),
        "counterparty": b.counterparty or "", "text": b.text, "source": b.category_source or "fallback",
    } for b in ds.bookings]
    return pd.DataFrame(rows)


def net_to_gross(cfg: Config, age: int | None) -> float:
    table = cfg.get_path("pension.income.net_to_gross", {"0": 0.87})
    best = 0.87
    for k, v in sorted(table.items(), key=lambda kv: int(kv[0])):
        if age is None or age >= int(k):
            best = v
    return best


def estimate_p2(cfg: Config, age: int, gross: float) -> float:
    """Mandatory BVG savings if the client's pension statement is unknown (rough)."""
    bvg = cfg["pension"]["bvg"]
    coord = max(0.0, min(gross, bvg["max_insured_salary"]) - bvg["coordination_deduction"])
    credits = sorted((int(k), v) for k, v in bvg["age_credits"].items())
    total = 0.0
    for a in range(25, max(age, 25)):
        rate = [v for k, v in credits if a >= k]
        total = total * (1 + bvg["min_interest"]) + coord * (rate[-1] if rate else 0)
    return total


def build_profile(ds: Dataset, cfg: Config, overrides: dict[str, float] | None = None) -> Profile:
    load_plugins()
    tax = load_taxonomy()
    if any(b.category is None for b in ds.bookings):
        Categoriser().categorise(ds)
    book = AssumptionBook(overrides)
    notes: list[DataNote] = [DataNote(level="warning", message=w) for w in ds.client.extra.get("adapter_warnings", [])]
    as_of = ds.as_of
    age = as_of.year - ds.client.birth_year if ds.client.birth_year else None

    df = _frame(ds)
    ext = df[df["category"] != "internal_transfer"].copy()
    ext["ym"] = ext["booking_date"].map(lambda d: (d.year, d.month))

    # ---- analysis window & coverage ----
    last_complete = month_start(as_of) if (as_of + timedelta(days=1)).day == 1 else add_months(month_start(as_of), -1)
    window_start = add_months(last_complete, -11)
    window_end = add_months(last_complete, 1) - timedelta(days=1)
    months = [add_months(window_start, i) for i in range(12)]
    main_acct = df["account_id"].value_counts().index[0] if len(df) else None
    active_months = set(df[df["account_id"] == main_acct]["booking_date"].map(lambda d: (d.year, d.month)))
    covered = [m for m in months if (m.year, m.month) in active_months]
    missing = [ym(m) for m in months if (m.year, m.month) not in active_months]
    n_cov = max(len(covered), 1)
    first = df["booking_date"].min() if len(df) else as_of
    history_months = (as_of.year - first.year) * 12 + as_of.month - first.month + 1
    if missing:
        notes.append(DataNote(level="warning", message=f"No bookings in {', '.join(missing)}: excluded from monthly averages"))
    if history_months < 13:
        notes.append(DataNote(level="warning", message=f"Only {history_months} months of history: annual bills may be missed"))

    covered_keys = {(m.year, m.month) for m in covered}
    win = ext[(ext["booking_date"] >= window_start) & (ext["booking_date"] <= window_end) & ext["ym"].isin(covered_keys)]

    # ---- recurring ----
    recurring = detect_recurring(ext, as_of)
    rec_ids_active = {bid for r in recurring if r.active for bid in r.booking_ids}
    rec_ids_ended = {bid for r in recurring if not r.active for bid in r.booking_ids}

    # ---- income ----
    sal = win[win["category"] == "income_salary"]
    salary_annual, payment_total, has_13th, employer = 0.0, 0.0, False, None
    for merchant, g in sal.groupby("merchant"):
        if len(g) < 3:
            continue
        employer = employer or merchant
        per_month = g.groupby("ym")["amount"].agg(["sum", "max", "count"]).sort_index()
        regular = float(np.median(per_month["max"].tail(3)))
        extra_months = per_month[per_month["count"] >= 2]
        thirteenth = float(extra_months["sum"].iloc[-1] - extra_months["max"].iloc[-1]) if len(extra_months) else 0.0
        has_13th = has_13th or thirteenth > 0.6 * regular
        salary_annual += regular * 12 + (thirteenth if thirteenth > 0.6 * regular else 0.0)
        payment_total += regular
    if employer is None and len(sal):
        salary_annual = float(sal["amount"].sum()) / n_cov * 12
        payment_total = salary_annual / 12
    monthly_income_series = win[win["category"].isin(tax.of_kind("income"))].groupby("ym")["amount"].sum()
    cv = float(monthly_income_series.std() / monthly_income_series.mean()) if len(monthly_income_series) > 2 else 0.0

    # ---- flows per category ----
    flows: dict[str, CategoryFlow] = {}
    for cat, g in win.groupby("category"):
        kind = tax.kind(cat)
        sign = 1.0 if kind == "income" else -1.0
        is_active = g["id"].isin(rec_ids_active)
        is_ended = g["id"].isin(rec_ids_ended)
        fixed = sum(sign * r.monthly_equivalent for r in recurring if r.active and r.category == cat)
        variable = sign * float(g[~is_active & ~is_ended]["amount"].sum()) / n_cov
        merchants = g.groupby("merchant")["amount"].agg(["sum", "count"]).sort_values("sum", ascending=kind != "income")
        flows[cat] = CategoryFlow(
            category=cat, kind=kind, label=tax.label(cat), monthly=round(fixed + variable, 2),
            fixed_monthly=round(fixed, 2), variable_monthly=round(variable, 2), n_bookings=len(g),
            opaque=tax.is_(cat, "opaque"), discretionary=tax.is_(cat, "discretionary"),
            top_merchants=[MerchantTotal(merchant=m, monthly=round(sign * s / n_cov, 2), count=int(c))
                           for m, (s, c) in merchants.head(5).iterrows()],
        )
    if "income_salary" in flows and employer:
        f = flows["income_salary"]
        f.monthly, f.fixed_monthly, f.variable_monthly = round(salary_annual / 12, 2), round(salary_annual / 12, 2), 0.0

    spending = [f for f in flows.values() if f.kind == "spending"]
    spending_monthly = sum(f.monthly for f in spending)
    fixed_costs = sum(f.fixed_monthly for f in spending)
    other_income = sum(f.monthly for f in flows.values() if f.kind == "income" and f.category != "income_salary")
    income_monthly = salary_annual / 12 + other_income
    contrib = {"p3a": 0.0, "invested": 0.0}
    for f in flows.values():
        if f.kind == "saving":
            bucket = tax.categories[f.category].get("saving_bucket", "invested")
            contrib[bucket] = contrib.get(bucket, 0.0) + f.monthly
    fcf = income_monthly - spending_monthly

    # ---- gross income ----
    if ds.client.gross_income_annual:
        gross = book.get("gross_income_annual", ds.client.gross_income_annual, label="Gross annual income",
                         source="client_data", unit="CHF/yr", step=1000)
        gross_src = "user" if "gross_income_annual" in book.overrides else "client_data"
    else:
        ratio = net_to_gross(cfg, age)
        gross = book.get("gross_income_annual", salary_annual / ratio, label="Gross annual income (estimated from net salary)",
                         source="market_default", unit="CHF/yr", low=salary_annual / 0.92, high=salary_annual / 0.80,
                         needs_confirmation=True, step=1000,
                         note=f"Net salary / {ratio:.2f} (typical social contributions)")
        gross_src = "user" if "gross_income_annual" in book.overrides else "market_default"

    # ---- balances ----
    by_account = {a.name or a.id: a.balance for a in ds.accounts}
    liquid = sum(a.balance for a in ds.accounts if a.type in LIQUID_TYPES)
    invested = sum(a.balance for a in ds.accounts if a.type == "securities") + sum(p.value for p in ds.positions)
    p3a = sum(a.balance for a in ds.accounts if a.type == "3a") + (ds.client.pension.pillar3a_balance or 0.0)
    if ds.client.pension.pillar2_balance is not None:
        p2 = book.get("pillar2_balance", ds.client.pension.pillar2_balance, label="Pension fund (pillar 2) savings",
                      source="client_data", step=1000)
        p2_src = "client_data"
    else:
        p2 = book.get("pillar2_balance", estimate_p2(cfg, age or 40, gross), label="Pension fund (pillar 2) savings",
                      source="market_default", needs_confirmation=True, step=1000,
                      note="Estimated from age and salary (mandatory minimum); check the pension statement")
        p2_src = "market_default"

    # ---- trend & reconciliation ----
    liquid_ids = {a.id for a in ds.accounts if a.type in LIQUID_TYPES}
    last12 = df[(df["account_id"].isin(liquid_ids)) & (df["booking_date"] > add_months(month_start(as_of), -11) - timedelta(days=1))]
    change = float(last12["amount"].sum())
    direction = "up" if change > 0.02 * max(liquid, 1) else "down" if change < -0.02 * max(liquid, 1) else "flat"
    implied = (fcf - sum(contrib.values())) * 12
    if not missing:
        notes.append(DataNote(level="info", message=f"Flows explain the balance change: implied {implied:,.0f} vs actual {change:,.0f} CHF over 12 months"))

    fallback_share = float((win["source"] == "fallback").mean()) if len(win) else 0.0
    if fallback_share > 0.05:
        notes.append(DataNote(level="warning", message=f"{fallback_share:.0%} of bookings could not be categorised"))

    opaque = {f.category: round(f.monthly, 2) for f in spending if f.opaque and f.monthly > 0}
    opaque_total = sum(opaque.values())

    ctx = HintContext(ds=ds, window=win, history=ext, recurring=recurring, flows=flows, covered_months=n_cov, taxonomy=tax)
    hints = [h for det in HINT_DETECTORS.values() for h in det(ctx)]

    return Profile(
        client_id=ds.client.id, as_of=as_of, age=age, window_start=window_start, window_months=12,
        covered_months=len(covered), missing_months=missing, history_months=history_months,
        income=IncomeProfile(salary_net_monthly_avg=round(salary_annual / 12, 2), salary_payment=round(payment_total, 2),
                             has_13th=has_13th, employer=employer, other_income_monthly=round(other_income, 2),
                             volatility_cv=round(cv, 3), gross_annual=round(gross, 2), gross_source=gross_src),
        flows=sorted(flows.values(), key=lambda f: (f.kind != "income", -f.monthly)),
        spending_monthly=round(spending_monthly, 2), fixed_costs_monthly=round(fixed_costs, 2),
        variable_costs_monthly=round(spending_monthly - fixed_costs, 2),
        saving_contrib_monthly={k: round(v, 2) for k, v in contrib.items()},
        free_cash_flow_monthly=round(fcf, 2), savings_rate=round(fcf / income_monthly, 3) if income_monthly else 0.0,
        balances=Balances(liquid=round(liquid, 2), invested=round(invested, 2), p3a=round(p3a, 2), p2=round(p2, 2),
                          p2_source=p2_src, by_account=by_account),
        buffer_months=round(liquid / fixed_costs, 1) if fixed_costs > 0 else 99.0,
        trend=Trend(liquid_12m_ago=round(liquid - change, 2), liquid_now=round(liquid, 2), change=round(change, 2), direction=direction),
        opaque_monthly=round(opaque_total, 2), opaque_share=round(opaque_total / spending_monthly, 3) if spending_monthly else 0.0,
        opaque_breakdown=opaque, recurring=recurring, hints=hints, data_quality=notes, assumptions=book.list(),
    )
