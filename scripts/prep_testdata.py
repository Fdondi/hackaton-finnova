"""One-off: the organisers' testdata (relational CSVs, ~1.2 GB) -> compact parquet + population statistics.

    uv run python scripts/prep_testdata.py [--src testdata/testdata] [--out data/testdata]

Writes (the `testdata` adapter and the population service read these, never the raw CSVs):
  bookings.parquet   personal liquid-account transactions joined with their event (vendor, MCC), sorted by client
  clients.parquet    one row per individual: master data, state, selected attributes, children from birth events
  accounts.parquet   accounts with their latest balance
  events.parquet     life events (birth, marriage, divorce, job change, ...) with parsed effects
  population/risk.json         big-bill rates and sizes, salary interruptions, spending noise per segment
  population/life_events.json  what changed for people after a life event (seasonally adjusted before/after)
  population/prices.json       median property value per canton (owners in the data)
  shortlist.json               story-rich demo clients

Periods stay raw (months: year = (p-1)//12, month = (p-1)%12+1); the adapter maps them to dates.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import yaml

ROOT = Path(__file__).resolve().parent.parent
LIQUID_KINDS = {"checking", "savings", "credit_card"}
LIFE_EVENTS = ["birth", "marriage", "divorce", "job_change", "migration", "death", "property_purchase", "income",
               "pillar3a_withdrawal", "savings_adjustment"]
BIG_BILL = 1000.0                   # CHF, one purchase
MIN_EVENT_N = 20                    # below this an effect is stored as "insufficient"
PRE, POST = 4, 4                    # months compared before / after an event (event month excluded)
MAPPING = yaml.safe_load((ROOT / "mygoal" / "adapters" / "mappings" / "testdata.yaml").read_text(encoding="utf-8"))
# not surprises: pension top-ups booked as purchases, and life-event costs (weddings, divorces) modelled as life events
NOT_A_BILL = "|".join(["säule", "3a", "vorsorge", *MAPPING["one_off_keywords"]])
SPEND_CATS = ["food", "restaurants", "transport", "other", "recreation", "health", "clothing", "communication",
              "education", "rent", "mortgage"]


def log(msg: str, t0: float) -> None:
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def age_band(age: float) -> str:
    return "18-29" if age < 30 else "30-44" if age < 45 else "45-64" if age < 65 else "65+"


def emp_group(e: str) -> str:
    return e if e in ("employed", "self_employed", "retired", "student") else "other"


def seg_key(age: float, emp: str) -> str:
    return f"{age_band(age)}|{emp_group(emp)}"


def q(values, qs=(0.25, 0.5, 0.75)) -> list[float]:
    return [round(float(x), 2) for x in np.quantile(values, qs)] if len(values) else []


def median_ci(values: np.ndarray, rng: np.random.Generator, n_boot: int = 1000) -> list[float]:
    if len(values) < 5:
        return []
    boots = np.median(rng.choice(values, size=(n_boot, len(values)), replace=True), axis=1)
    return [round(float(np.percentile(boots, 5)), 2), round(float(np.percentile(boots, 95)), 2)]


# ---------------------------------------------------------------------------------------------------- tables
def load_tables(src: Path, t0: float):
    acc = pd.read_csv(src / "account.csv", dtype=str, keep_default_na=False)
    bal = pd.read_csv(src / "account_balance.csv", dtype={"account_id": str, "period": int, "balance_chf": float})
    acc = acc.merge(bal[["account_id", "period", "balance_chf"]].rename(columns={"period": "balance_period"}),
                    on="account_id", how="left")
    acc["business"] = acc["product_name"].str.startswith("Geschaeftskonto")
    ind = pd.read_csv(src / "individual.csv", dtype=str, keep_default_na=False)
    st = pd.read_csv(src / "individual_state.csv", dtype=str, keep_default_na=False)
    emp = pd.read_csv(src / "employer.csv", dtype=str, keep_default_na=False)
    log(f"master data: {len(ind)} individuals, {len(acc)} accounts, {len(emp)} employers", t0)

    ev = pacsv.read_csv(src / "event.csv", convert_options=pacsv.ConvertOptions(
        include_columns=["event_id", "individual_id", "counterparty_id", "period", "type", "effects"],
        column_types={"period": pa.int32(), "counterparty_id": pa.string()})).to_pandas()
    log(f"events: {len(ev)}", t0)
    eff = [json.loads(s) if s else {} for s in ev["effects"]]
    ev["vendor"] = [e.get("vendor") for e in eff]
    ev["mcc"] = [str(e["mcc"]) if e.get("mcc") else None for e in eff]
    ev["mcc_description"] = [e.get("mcc_description") for e in eff]
    life = ev[ev["type"].isin(LIFE_EVENTS)].copy()
    life["effects_obj"] = [eff[i] for i in life.index]
    log("event effects parsed", t0)

    tx = pacsv.read_csv(src / "transaction.csv", convert_options=pacsv.ConvertOptions(column_types={
        "period": pa.int32(), "amount_chf": pa.float64(), "day_of_month": pa.int8()})).to_pandas()
    log(f"transactions: {len(tx)}", t0)
    return acc, ind, st, emp, ev, life, tx


def build_bookings(tx: pd.DataFrame, acc: pd.DataFrame, ev: pd.DataFrame, t0: float) -> pd.DataFrame:
    a = acc[["account_id", "individual_id", "kind", "business"]]
    b = tx.merge(a, on="account_id", how="inner")
    b = b[b["kind"].isin(LIQUID_KINDS) & ~b["business"] & (b["category"] != "initial_balance")]
    e = ev[["event_id", "type", "vendor", "mcc", "mcc_description"]].rename(
        columns={"event_id": "source_event_id", "type": "event_type"})
    b = b.merge(e, on="source_event_id", how="left")
    b = b.rename(columns={"amount_chf": "amount", "day_of_month": "day"})
    b["day"] = b["day"].fillna(0).astype("int8")
    b = b[["individual_id", "txn_id", "account_id", "period", "day", "amount", "category", "event_type", "vendor",
           "mcc", "mcc_description"]].sort_values(["individual_id", "period", "day", "txn_id"]).reset_index(drop=True)
    log(f"bookings kept (personal liquid accounts, no opening balances): {len(b)}", t0)
    return b


def build_clients(ind, st, emp, life, bookings, window) -> pd.DataFrame:
    attrs = ind["attributes"].map(json.loads)
    c = pd.DataFrame({
        "individual_id": ind["individual_id"], "first_name": attrs.map(lambda a: a.get("first_name")),
        "last_name": attrs.map(lambda a: a.get("last_name")), "sex": ind["sex"],
        "birth_period": ind["birth_period"].astype(int),
        "death_period": pd.to_numeric(ind["death_period"], errors="coerce").astype("Int32"),
        "canton": attrs.map(lambda a: a.get("canton")), "plz": attrs.map(lambda a: a.get("plz")),
        "city": attrs.map(lambda a: a.get("city")), "occupation": attrs.map(lambda a: a.get("occupation")),
        "nationality": attrs.map(lambda a: a.get("nationality")), "education": attrs.map(lambda a: a.get("education")),
        "risk_appetite": attrs.map(lambda a: a.get("risk_appetite")), "wallet_share": attrs.map(lambda a: a.get("wallet_share")),
        "owns_property": attrs.map(lambda a: bool(a.get("owns_property"))),
        "property_value": attrs.map(lambda a: a.get("property_value")),
        "mortgage_outstanding": attrs.map(lambda a: a.get("mortgage_outstanding")),
        "mortgage_monthly": attrs.map(lambda a: a.get("mortgage_monthly")),
        "fixed_rent": attrs.map(lambda a: a.get("fixed_rent")),
        "interest_travel": attrs.map(lambda a: (a.get("interests") or {}).get("Reisen")),
        "interests": attrs.map(lambda a: json.dumps([k for k, v in sorted((a.get("interests") or {}).items(), key=lambda kv: -kv[1])
                                                     if v >= 0.6][:4], ensure_ascii=False)),
        "health_conditions": attrs.map(lambda a: ",".join(a.get("health_conditions") or [])),
        "churn_reason": attrs.map(lambda a: a.get("churn_reason")),
        "onboarded_period": attrs.map(lambda a: a.get("onboarded_period")),
    })
    s = st[["individual_id", "income_chf", "employer_id", "marital_status", "education_level", "employment_type"]].copy()
    s["income_chf"] = pd.to_numeric(s["income_chf"], errors="coerce").fillna(0.0)
    s = s.merge(emp[["employer_id", "sector"]].rename(columns={"sector": "employer_sector"}), on="employer_id", how="left")
    c = c.merge(s, on="individual_id", how="left")
    # children seen being born in the data (both parents)
    births = life[life["type"] == "birth"]
    kids: dict[str, list[int]] = {}
    for iid, cp, p in zip(births["individual_id"], births["counterparty_id"], births["period"]):
        for parent in (iid, cp):
            if isinstance(parent, str) and parent:
                kids.setdefault(parent, []).append(int(p))
    c["children_birth_periods"] = c["individual_id"].map(lambda i: json.dumps(kids.get(i, [])))
    w = bookings[bookings["period"].between(*window)]
    c = c.merge(w.groupby("individual_id")["period"].nunique().rename("n_months"), on="individual_id", how="left")
    c = c.merge(w[w["event_type"] == "salary"].groupby("individual_id")["period"].nunique().rename("n_salary_months"),
                on="individual_id", how="left")
    c = c.merge(bookings.groupby("individual_id").size().rename("n_bookings"), on="individual_id", how="left")
    for col in ("n_months", "n_salary_months", "n_bookings"):
        c[col] = c[col].fillna(0).astype(int)
    c["age"] = (window[1] - c["birth_period"]) // 12
    return c


# ---------------------------------------------------------------------------------------------------- population
def monthly_panel(bookings: pd.DataFrame, people: pd.Index, window) -> tuple[pd.DataFrame, pd.DataFrame]:
    w = bookings[bookings["period"].between(*window) & bookings["individual_id"].isin(people)].copy()
    w["out"] = np.where(w["category"].isin(SPEND_CATS) & (w["amount"] < 0), -w["amount"], 0.0)
    w["big"] = (w["event_type"] == "purchase") & (w["amount"] <= -BIG_BILL) \
        & ~w["vendor"].fillna("").str.lower().str.contains(NOT_A_BILL, regex=True)
    w["var_small"] = np.where((w["event_type"] == "purchase") & (w["amount"] > -BIG_BILL), w["out"], 0.0)
    w["salary"] = np.where(w["event_type"] == "salary", w["amount"], 0.0)
    idx = pd.MultiIndex.from_product([people, range(window[0], window[1] + 1)], names=["individual_id", "period"])
    pm = w.groupby(["individual_id", "period"])[["out", "var_small", "salary"]].sum().reindex(idx, fill_value=0.0)
    return pm, w


def salary_spells(sal: np.ndarray) -> list[int]:
    """Runs of zero-salary months bounded by salary months on both sides (a real interruption, not a start/end)."""
    paid = sal > 0
    spells, run, seen_paid = [], 0, False
    for p in paid:
        if p:
            if seen_paid and run:
                spells.append(run)
            run, seen_paid = 0, True
        elif seen_paid:
            run += 1
    return spells


def risk_stats(clients: pd.DataFrame, pm: pd.DataFrame, w: pd.DataFrame, life: pd.DataFrame, window) -> dict:
    months = window[1] - window[0] + 1
    people = clients.set_index("individual_id")
    big = w[w["big"]]
    per_person_big = big.groupby("individual_id")["amount"].agg(["count", "sum"])
    var = pm["var_small"].unstack()
    cv = (var.std(axis=1) / var.mean(axis=1).replace(0, np.nan)).dropna()
    sal = pm["salary"].unstack()
    earners = sal[(sal > 0).sum(axis=1) >= 6]
    spells = {iid: salary_spells(row.to_numpy()) for iid, row in earners.iterrows()}

    def seg_stats(ids: pd.Index) -> dict:
        ids = ids.intersection(var.index)
        sizes = -big[big["individual_id"].isin(ids)]["amount"].to_numpy()
        n = len(ids)
        logs = np.log(sizes) if len(sizes) else np.array([np.log(2 * BIG_BILL)])
        e_ids = ids.intersection(earners.index)
        sp = [s for i in e_ids for s in spells[i]]
        out = {
            "n_people": int(n),
            "bill_rate": round(len(sizes) / max(n, 1) / months * 12, 3),           # bills >= threshold per year
            "bill_mu": round(float(logs.mean()), 4), "bill_sigma": round(float(logs.std()) if len(logs) > 1 else 0.8, 4),
            "bill_p50": round(float(np.median(sizes)), 0) if len(sizes) else None,
            "bill_p90": round(float(np.quantile(sizes, 0.9)), 0) if len(sizes) else None,
            "share_with_bill": round(float(per_person_big.index.isin(ids).sum()) / max(n, 1), 3),
            "spend_noise_cv": round(float(cv[cv.index.isin(ids)].median()), 3) if cv.index.isin(ids).any() else None,
            "n_earners": int(len(e_ids)),
            "interrupt_prob": round(len(sp) / max(len(e_ids), 1) / months * 12, 4) if len(e_ids) else None,
            "interrupt_median_months": float(np.median(sp)) if sp else None,
            "n_spells": len(sp),
        }
        return out

    seg = people["age"].combine(people["employment_type"], lambda a, e: seg_key(a, e))
    segments = {"all": seg_stats(people.index)}
    for key, ids in seg.groupby(seg).groups.items():
        segments[key] = seg_stats(pd.Index(ids))
    by_sector = {}
    for sector, ids in people.groupby("employer_sector").groups.items():
        if sector:
            s = seg_stats(pd.Index(ids))
            by_sector[sector] = {k: s[k] for k in ("n_earners", "interrupt_prob", "interrupt_median_months", "n_spells")}

    causes = big.assign(size=-big["amount"]).groupby("vendor")["size"].agg(["count", "median"]).sort_values("count", ascending=False)
    total = len(big)
    top_causes = [{"vendor": v, "share": round(r["count"] / total, 3), "median": round(float(r["median"]), 0),
                   "count": int(r["count"])} for v, r in causes.head(8).iterrows()]
    desc = big.assign(size=-big["amount"]).groupby("mcc_description")["size"].agg(["count", "median"]).sort_values("count", ascending=False)
    top_kinds = [{"kind": k, "share": round(r["count"] / total, 3), "median": round(float(r["median"]), 0)}
                 for k, r in desc.head(6).iterrows()]

    # job changes: new income vs the salary paid in the months before
    jc = life[(life["type"] == "job_change") & life["individual_id"].isin(sal.index)]
    ratios = []
    for iid, p, e in zip(jc["individual_id"], jc["period"], jc["effects_obj"]):
        pre = sal.loc[iid, [x for x in range(p - 3, p) if window[0] <= x <= window[1]]]
        pre = pre[pre > 0]
        new = float(e.get("new_income_chf") or 0)
        if len(pre) and new > 0:
            ratios.append(new / float(pre.median()))
    ratios = np.array(ratios)
    n_emp = int((people["employment_type"].isin(["employed", "self_employed"])).sum())
    job = {"n": int(len(ratios)), "annual_rate": round(len(jc) / max(n_emp, 1) / months * 12, 4),
           "share_cut": round(float((ratios < 0.98).mean()), 3) if len(ratios) else None,
           "median_change_pct": round(float(np.median(ratios) - 1), 4) if len(ratios) else None,
           "p10_change_pct": round(float(np.quantile(ratios, 0.1) - 1), 4) if len(ratios) else None,
           "p90_change_pct": round(float(np.quantile(ratios, 0.9) - 1), 4) if len(ratios) else None,
           "cut_median_pct": round(float(np.median(ratios[ratios < 0.98]) - 1), 4) if (ratios < 0.98).any() else None,
           "ratio_quantiles": [round(float(x), 4) for x in np.quantile(ratios, np.linspace(0.05, 0.95, 19))] if len(ratios) else []}
    return {"window": list(window), "months": months, "big_bill_threshold": BIG_BILL, "segments": segments,
            "by_sector": by_sector, "top_causes": top_causes, "top_kinds": top_kinds, "job_change": job}


def life_event_stats(clients: pd.DataFrame, pm: pd.DataFrame, life: pd.DataFrame, window, rng) -> dict:
    panel = pm
    seasonal = panel.groupby("period")[["out", "salary"]].mean()
    sex = clients.set_index("individual_id")["sex"]
    people = set(panel.index.get_level_values(0))
    out: dict[str, dict] = {}
    for etype in ["birth", "marriage", "divorce", "job_change", "migration", "income", "property_purchase", "pillar3a_withdrawal"]:
        e = life[life["type"] == etype]
        pairs = [(i, int(p), "self") for i, p in zip(e["individual_id"], e["period"])]
        if etype in ("birth", "marriage", "divorce"):
            pairs += [(c, int(p), "partner") for c, p in zip(e["counterparty_id"], e["period"]) if isinstance(c, str) and c]
        rows = []
        for iid, p, role in pairs:
            if iid not in people:
                continue
            pre_p = [x for x in range(p - PRE, p) if x >= window[0]]
            post_p = [x for x in range(p + 1, p + POST + 1) if x <= window[1]]
            if len(pre_p) < 2 or len(post_p) < 2:
                continue
            s = panel.loc[iid]
            adj = lambda col, ps: float(s.loc[ps, col].mean() - seasonal.loc[ps, col].mean())  # noqa: E731
            row = {"id": iid, "sex": sex.get(iid), "role": role,
                   "d_spend": adj("out", post_p) - adj("out", pre_p),
                   "d_salary": adj("salary", post_p) - adj("salary", pre_p),
                   "one_off": float(s.loc[p, "out"] - seasonal.loc[p, "out"]) - adj("out", pre_p),
                   "pre_spend": float(s.loc[pre_p, "out"].mean()), "pre_salary": float(s.loc[pre_p, "salary"].mean())}
            rows.append(row)
        if not rows:
            out[etype] = {"n": 0, "status": "insufficient"}
            continue
        df = pd.DataFrame(rows)
        n = len(df)

        def summ(col, d=df):
            v = d[col].to_numpy()
            return {"median": round(float(np.median(v)), 0), "mean": round(float(v.mean()), 0),
                    "iqr": [round(x, 0) for x in q(v, (0.25, 0.75))], "ci90": median_ci(v, rng)}
        res = {"n": n, "n_events": int(len(e)), "status": "ok" if n >= MIN_EVENT_N else "insufficient",
               "d_spend": summ("d_spend"), "d_salary": summ("d_salary"), "one_off": summ("one_off"),
               "pre_spend_median": round(float(df["pre_spend"].median()), 0),
               "pre_salary_median": round(float(df["pre_salary"].median()), 0)}
        if etype == "birth":
            res["by_sex"] = {sx: {"n": int(len(g)), "d_salary": summ("d_salary", g), "d_spend": summ("d_spend", g)}
                             for sx, g in df.groupby("sex")}
        out[etype] = res
    return {"window": list(window), "months_before": PRE, "months_after": POST, "min_n": MIN_EVENT_N,
            "method": "per person: mean of the months after minus the months before (event month excluded), "
                      "each adjusted by the population average of the same months (seasonality)",
            "events": out}


def category_moves(cat_panel: pd.DataFrame, life: pd.DataFrame, window, etypes) -> dict[str, list[dict]]:
    seasonal = cat_panel.groupby("period").mean()
    people = set(cat_panel.index.get_level_values(0))
    out = {}
    for etype in etypes:
        e = life[life["type"] == etype]
        pairs = list(zip(e["individual_id"], e["period"]))
        if etype in ("birth", "marriage", "divorce"):
            pairs += [(c, p) for c, p in zip(e["counterparty_id"], e["period"]) if isinstance(c, str) and c]
        deltas = []
        for iid, p in pairs:
            if iid not in people:
                continue
            pre_p = [x for x in range(p - PRE, p) if x >= window[0]]
            post_p = [x for x in range(p + 1, p + POST + 1) if x <= window[1]]
            if len(pre_p) < 2 or len(post_p) < 2:
                continue
            s = cat_panel.loc[iid]
            d = (s.loc[post_p].mean() - seasonal.loc[post_p].mean()) - (s.loc[pre_p].mean() - seasonal.loc[pre_p].mean())
            deltas.append(d)
        if not deltas:
            continue
        med = pd.DataFrame(deltas).mean().sort_values(key=abs, ascending=False)   # means: medians of sparse cats are 0
        out[etype] = [{"category": k, "mean_change": round(float(v), 0)} for k, v in med.head(4).items() if abs(v) >= 20]
    return out


def event_costs(w: pd.DataFrame, life: pd.DataFrame, etypes) -> dict[str, dict]:
    """Big purchases (>= BIG_BILL) both partners made in the event month, summed per event: weddings, lawyers, ..."""
    big = w[(w["event_type"] == "purchase") & (w["amount"] <= -BIG_BILL)
            & ~w["vendor"].fillna("").str.lower().str.contains("säule|3a|vorsorge", regex=True)]
    out = {}
    for etype in etypes:
        e = life[life["type"] == etype]
        totals, vendors = [], Counter()
        for iid, cp, p in zip(e["individual_id"], e["counterparty_id"], e["period"]):
            who = [iid] + ([cp] if isinstance(cp, str) and cp else [])
            x = big[big["individual_id"].isin(who) & (big["period"] == p)]
            totals.append(float(-x["amount"].sum()))
            vendors.update(x["vendor"].dropna())
        t = np.array(totals)
        if not len(t):
            continue
        paid = t[t > 0]
        out[etype] = {"n_events": int(len(t)), "share_with_costs": round(float((t > 0).mean()), 3),
                      "median_if_any": round(float(np.median(paid)), 0) if len(paid) else 0.0,
                      "iqr_if_any": [round(x, 0) for x in q(paid, (0.25, 0.75))] if len(paid) else [],
                      "top_vendors": [{"vendor": v, "count": c} for v, c in vendors.most_common(4)]}
    return out


def property_prices(clients: pd.DataFrame) -> dict:
    own = clients[clients["owns_property"] & clients["property_value"].notna()]
    by_canton = own.groupby("canton")["property_value"].agg(["median", "count"])
    return {"overall_median": round(float(own["property_value"].median()), -3), "n": int(len(own)),
            "by_canton": {k: {"median": round(float(r["median"]), -3), "n": int(r["count"])} for k, r in by_canton.iterrows()}}


# ---------------------------------------------------------------------------------------------------- shortlist
def shortlist(clients: pd.DataFrame, w: pd.DataFrame, life: pd.DataFrame, accounts: pd.DataFrame, per_tag: int = 2) -> list[dict]:
    """Story-rich employed adults, `per_tag` per story, moderate savings first (a demo needs a gap to close).
    scripts/pick_demo_clients.py re-ranks a longer list of these with the engine."""
    liquid = accounts[accounts["kind"].isin(LIQUID_KINDS) & ~accounts["business"] & (accounts["closed_period"] == "")] \
        .groupby("individual_id")["balance_chf"].sum()
    c = clients.set_index("individual_id")
    c["liquid"] = liquid.reindex(c.index).fillna(0.0)
    ok = c[c["death_period"].isna() & c["age"].between(25, 60) & (c["employment_type"] == "employed")
           & (c["n_salary_months"] >= 10) & (c["n_months"] >= 11) & c["liquid"].between(5_000, 150_000)]
    rent = set(w[w["event_type"] == "rent"]["individual_id"])
    biggest = w[w["big"]].sort_values("amount").groupby("individual_id").head(1).set_index("individual_id")
    picks: list[dict] = []
    used: set[str] = set()

    def add(ids, story, tag, k=None):
        for iid in [i for i in ids if i in ok.index and i not in used][:k or per_tag]:
            r = ok.loc[iid]
            used.add(iid)
            picks.append({"id": iid, "name": f"{r['first_name']} {r['last_name']}", "age": int(r["age"]), "canton": r["canton"],
                          "story": story(iid, r), "tag": tag, "renter": iid in rent, "liquid": round(float(r["liquid"]), 0)})

    def events_of(t):
        e = life[life["type"] == t]
        ids = list(e["individual_id"]) + ([x for x in e["counterparty_id"] if isinstance(x, str) and x] if t in ("birth", "marriage", "divorce") else [])
        return ids

    moderate = lambda i: abs(np.log(max(ok["liquid"].get(i, 1.0), 1.0) / 40_000))  # noqa: E731
    by_liquid = lambda ids: sorted(set(ids), key=moderate)  # noqa: E731
    renters_saving = ok[ok.index.isin(rent) & ok["age"].between(28, 42) & ~ok["owns_property"]]
    add(by_liquid(renters_saving.index), lambda i, r: "Renter saving for a home", "home")
    add(by_liquid([i for i in events_of("birth") if i in rent]), lambda i, r: "Became a parent this year", "baby")
    add(by_liquid(events_of("marriage")), lambda i, r: "Got married this year", "married")
    add(by_liquid(events_of("divorce")), lambda i, r: "Separated this year", "separated")
    add(by_liquid(events_of("job_change")), lambda i, r: "Changed job this year", "new_job")
    big_ids = [i for i in biggest.index if -biggest.loc[i, "amount"] >= 4000]
    add(by_liquid(big_ids),
        lambda i, r: f"Hit by a big bill: {biggest.loc[i, 'vendor']} CHF {-biggest.loc[i, 'amount']:,.0f}".replace(",", "'"), "big_bill")
    tight = ok[ok["liquid"] < ok["income_chf"] * 1.5].sort_values("income_chf", ascending=False)
    add(list(tight.index), lambda i, r: "Earns well but has little cash buffer", "tight")
    return picks


# ---------------------------------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "testdata" / "testdata"))
    ap.add_argument("--out", default=str(ROOT / "data" / "testdata"))
    ap.add_argument("--reset-shortlist", action="store_true", help="overwrite an engine-ranked shortlist.json")
    args = ap.parse_args()
    src, out = Path(args.src), Path(args.out)
    (out / "population").mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    rng = np.random.default_rng(20260918)

    acc, ind, st, emp, ev, life, tx = load_tables(src, t0)
    bookings = build_bookings(tx, acc, ev, t0)
    del tx
    last = int(bookings["period"].max())
    window = (last - 11, last)
    clients = build_clients(ind, st, emp, life, bookings, window)

    pq.write_table(pa.Table.from_pandas(bookings, preserve_index=False), out / "bookings.parquet",
                   row_group_size=65_536, compression="zstd")
    pq.write_table(pa.Table.from_pandas(clients, preserve_index=False), out / "clients.parquet")
    accounts = acc.drop(columns=[c for c in ("run_id",) if c in acc.columns])
    pq.write_table(pa.Table.from_pandas(accounts, preserve_index=False), out / "accounts.parquet")
    events = life.drop(columns=["effects_obj", "vendor", "mcc", "mcc_description"]).rename(columns={"type": "event_type"})
    pq.write_table(pa.Table.from_pandas(events, preserve_index=False), out / "events.parquet")
    log(f"parquet written to {out}", t0)

    pop = clients[clients["death_period"].isna() & (clients["age"] >= 18) & (clients["n_months"] >= 10)]
    pm, w = monthly_panel(bookings, pd.Index(pop["individual_id"]), window)
    cat_panel = w[w["category"].isin(SPEND_CATS)].pivot_table(index=["individual_id", "period"], columns="category",
                                                              values="out", aggfunc="sum")
    cat_panel = cat_panel.reindex(pm.index, fill_value=0.0).fillna(0.0)
    log(f"population panel: {len(pop)} people x {window[1] - window[0] + 1} months", t0)

    risk = risk_stats(pop, pm, w, life, window)
    (out / "population" / "risk.json").write_text(json.dumps(risk, indent=1, ensure_ascii=False))
    events_json = life_event_stats(pop, pm, life, window, rng)
    for etype, moves in category_moves(cat_panel, life, window, list(events_json["events"])).items():
        events_json["events"][etype]["categories"] = moves
    for etype, costs in event_costs(w, life, list(events_json["events"])).items():
        events_json["events"][etype]["event_costs"] = costs
    events_json["events"]["job_change"]["income_ratio"] = risk["job_change"]     # new salary / old, per job change
    (out / "population" / "life_events.json").write_text(json.dumps(events_json, indent=1, ensure_ascii=False))
    prices = property_prices(clients)
    (out / "population" / "prices.json").write_text(json.dumps(prices, indent=1, ensure_ascii=False))
    picks = shortlist(clients, w, life, acc)
    ranked = out / "shortlist.json"
    if args.reset_shortlist or not ranked.exists() or '"score"' not in ranked.read_text(encoding="utf-8"):
        ranked.write_text(json.dumps(picks, indent=1, ensure_ascii=False))   # keep an engine-ranked shortlist
    (out / "candidates.json").write_text(json.dumps(shortlist(clients, w, life, acc, per_tag=40), indent=1, ensure_ascii=False))
    meta = {"window": list(window), "last_period": last, "period_formula": "year=(p-1)//12, month=(p-1)%12+1",
            "rows": {"bookings": len(bookings), "clients": len(clients), "accounts": len(accounts), "events": len(events)},
            "population": len(pop), "big_bill_threshold": BIG_BILL}
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    log("population statistics written", t0)

    a = risk["segments"]["all"]
    print(f"\nwindow {window}  population {len(pop)}")
    print(f"big bills: {a['bill_rate']}/yr, median {a['bill_p50']}, p90 {a['bill_p90']}, {a['share_with_bill']:.0%} of people; "
          f"salary interruptions {a['interrupt_prob']}/yr, median {a['interrupt_median_months']} months; "
          f"spending noise cv {a['spend_noise_cv']}")
    print("job change:", risk["job_change"])
    for k, v in events_json["events"].items():
        c = v.get("event_costs", {})
        print(f"  {k:20s} n={v['n']:4d} {v['status']:12s}", {x: v[x]["median"] for x in ("d_spend", "d_salary") if x in v},
              f"costs {c.get('share_with_costs')} x {c.get('median_if_any')}", [t["vendor"][:30] for t in c.get("top_vendors", [])][:2])
    print("shortlist:", [(p["name"], p["tag"]) for p in picks])


if __name__ == "__main__":
    main()
