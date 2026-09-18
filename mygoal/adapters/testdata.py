"""The organisers' testdata (a population simulator: ~8k people, 12 months), prepared by scripts/prep_testdata.py.

Reads <data.dir>/*.parquet, never the raw 1.2 GB CSVs. The data's own event types and coarse categories map to our
taxonomy via mappings/testdata.yaml; what stays ambiguous (transport, "other") goes through the merchant/MCC rules.
Dates: `period` is a month number. With `data.shift_to_today` every date moves forward so the last data month is the
last complete month, and a data note says so. The data has no goals: config/goal_seeds.yaml provides starting ones.
"""
from __future__ import annotations

import calendar
import json
from datetime import date
from functools import cached_property

import numpy as np
import pyarrow.parquet as pq
import yaml

from ..config import Config, resolve_path
from ..model import Account, Booking, Client, Dataset, GoalSpec, Household, add_months, months_between
from .base import ClientSummary, register_adapter
from .tabular import MAPPINGS_DIR

_DICT_COLUMNS = ["individual_id", "account_id", "category", "event_type", "vendor", "mcc", "mcc_description"]


def period_to_date(p: int, day: int = 1) -> date:
    y, m = divmod(int(p) - 1, 12)
    return date(y, m + 1, min(max(int(day), 1), calendar.monthrange(y, m + 1)[1]))


@register_adapter("testdata")
class TestdataSource:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = resolve_path(cfg.get_path("app.data.dir", "data/testdata"))
        self.map = yaml.safe_load((MAPPINGS_DIR / "testdata.yaml").read_text(encoding="utf-8"))
        self.meta = json.loads((self.dir / "meta.json").read_text(encoding="utf-8"))
        self.shift = self._shift_months(cfg.get_path("app.data.shift_to_today", True))

    def _shift_months(self, setting) -> int:
        last = period_to_date(self.meta["last_period"])
        if setting in (False, None, "none", ""):
            return 0
        if isinstance(setting, str) and len(setting) == 7:          # pinned "YYYY-MM"
            target = date(int(setting[:4]), int(setting[5:]), 1)
        else:                                                       # last complete month before today
            target = add_months(date.today().replace(day=1), -1)
        return months_between(last, target)

    def to_date(self, period: int, day: int = 1) -> date:
        return period_to_date(int(period) + self.shift, day)

    # ---- tables (loaded once, lazily) ----
    @cached_property
    def clients(self):
        return pq.read_table(self.dir / "clients.parquet").to_pandas().set_index("individual_id")

    @cached_property
    def accounts(self):
        return pq.read_table(self.dir / "accounts.parquet").to_pandas()

    @cached_property
    def _bookings(self):
        """The bookings table plus [start, end) row offsets per client (the file is sorted by client)."""
        table = pq.read_table(self.dir / "bookings.parquet", read_dictionary=_DICT_COLUMNS)
        col = table.column("individual_id").combine_chunks()
        codes = col.indices.to_numpy(zero_copy_only=False)
        edges = np.flatnonzero(np.diff(codes)) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [len(codes)]))
        ids = col.dictionary.to_pylist()
        return table, {ids[codes[s]]: (int(s), int(e)) for s, e in zip(starts, ends)}

    @cached_property
    def shortlist(self) -> list[dict]:
        path = self.dir / "shortlist.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    @cached_property
    def prices(self) -> dict:
        path = self.dir / "population" / "prices.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    # ---- DataSource ----
    def list_clients(self) -> list[ClientSummary]:
        c = self.clients
        last = self.meta["last_period"]
        ok = c[c["death_period"].isna() & ((last - c["birth_period"]) // 12 >= 20) & (c["n_months"] >= 6)]
        out, seen = [], set()
        for s in self.shortlist:
            if s["id"] in ok.index:
                out.append(ClientSummary(id=s["id"], name=f"★ {s['name']}, {s['age']} · {s['story']}", canton=s["canton"],
                                         birth_year=self.to_date(c.loc[s["id"], "birth_period"]).year))
                seen.add(s["id"])
        labels: set[str] = set()
        for iid, r in ok.sort_values(["first_name", "last_name"]).iterrows():
            if iid in seen:
                continue
            label = f"{r['first_name']} {r['last_name']}, {(last - r['birth_period']) // 12}, {r['canton']}"
            if label in labels:
                label += f" #{iid[:4]}"
            labels.add(label)
            out.append(ClientSummary(id=iid, name=label, canton=r["canton"], birth_year=self.to_date(r["birth_period"]).year,
                                     n_bookings=int(r["n_bookings"])))
        return out

    def load(self, client_id: str) -> Dataset:
        if client_id not in self.clients.index:
            raise KeyError(client_id)
        r = self.clients.loc[client_id]
        retired = r["employment_type"] == "retired"
        accounts = self._accounts(client_id)
        own = {a.id for a in accounts}
        table, offsets = self._bookings
        start, end = offsets.get(client_id, (0, 0))
        bookings = [self._booking(row, retired) for row in table.slice(start, end - start).to_pylist()
                    if row["account_id"] in own]
        as_of = self.to_date(self.meta["last_period"])
        as_of = as_of.replace(day=calendar.monthrange(as_of.year, as_of.month)[1])
        client = self._client(client_id, r, as_of, has_rent=any(b.bank_category == "housing" and b.extra.get("event_type") == "rent"
                                                                for b in bookings))
        return Dataset(client=client, accounts=accounts, bookings=bookings, as_of=as_of, source="testdata")

    # ---- mapping ----
    def _accounts(self, client_id: str) -> list[Account]:
        a = self.accounts
        rows = a[(a["individual_id"] == client_id) & ~a["business"] & (a["closed_period"] == "")]
        out = []
        for _, x in rows.iterrows():
            typ = self.map["accounts"].get(x["kind"])
            if typ:
                bal = x["balance_chf"]
                out.append(Account(id=x["account_id"], client_id=client_id, type=typ, name=x["product_name"],
                                   balance=0.0 if bal != bal else float(bal)))       # NaN-safe
        return out

    def _category(self, row: dict, retired: bool) -> tuple[str | None, str | None]:
        """(bank_category, fallback_category) for one booking."""
        et, cat, vendor = row["event_type"], row["category"], (row["vendor"] or "").lower()
        if et == "salary" and retired:
            return self.map["pension_category"], None
        if et in self.map["event_types"]:
            return self.map["event_types"][et], None
        if row["amount"] < 0 and any(k in vendor for k in self.map["one_off_keywords"]):
            return "life_event_costs", None
        if cat in self.map["categories"]:
            return self.map["categories"][cat], None
        return None, self.map["fallback"].get(cat)

    def _booking(self, row: dict, retired: bool) -> Booking:
        bank, fallback = self._category(row, retired)
        et = row["event_type"]
        vendor = row["vendor"] or self.map["counterparty"].get(et) or (row["category"] or "").replace("_", " ").title()
        if et == "salary" and retired:
            vendor = "Rente / Pension"
        text = vendor + (f" | {row['mcc_description']}" if row["mcc_description"] else "")
        mcc = row["mcc"]
        extra = {"event_type": et, "data_category": row["category"]}
        if fallback:
            extra["fallback_category"] = fallback
        return Booking(
            id=row["txn_id"], account_id=row["account_id"], booking_date=self.to_date(row["period"], row["day"] or 15),
            amount=round(float(row["amount"]), 2), text=text, counterparty=vendor, mcc=mcc, bank_category=bank,
            tags=list(self.map["tags_by_mcc"].get(mcc or "", [])), extra=extra,
        )

    def _client(self, client_id: str, r, as_of: date, has_rent: bool) -> Client:
        birth = self.to_date(r["birth_period"])
        kids = [self.to_date(p).year for p in json.loads(r["children_birth_periods"] or "[]")]
        age = as_of.year - birth.year
        story = next((s["story"] for s in self.shortlist if s["id"] == client_id), None)
        extra = {
            "segment_age": age, "employment_type": r["employment_type"] or None, "sector": r["employer_sector"] or None,
            "occupation": r["occupation"], "city": r["city"], "marital_status": r["marital_status"],
            "net_income_monthly_stated": float(r["income_chf"] or 0.0), "risk_appetite": r["risk_appetite"],
            "wallet_share": r["wallet_share"], "owns_property": bool(r["owns_property"]),
            "property_value": r["property_value"], "mortgage_outstanding": r["mortgage_outstanding"],
            "health_conditions": [h for h in (r["health_conditions"] or "").split(",") if h],
            "story": story, "renter": has_rent, "sex": r["sex"],
            "interests": json.loads(r["interests"]) if "interests" in r and r["interests"] else [],
            "adapter_notes": [f"Test data dates moved forward {self.shift} months so the latest month is "
                              f"{as_of:%b %Y} (source data ends {period_to_date(self.meta['last_period']):%b %Y})"]
                             if self.shift else [],
        }
        client = Client(id=client_id, name=f"{r['first_name']} {r['last_name']}", birth_year=birth.year, canton=r["canton"],
                        household=Household(adults=2 if r["marital_status"] == "married" else 1, children_birth_years=kids),
                        extra=extra)
        client.goals = self._seed_goals(client, r, as_of, age, has_rent)
        return client

    def _seed_goals(self, client: Client, r, as_of: date, age: int, renter: bool) -> list[GoalSpec]:
        seeds = self.cfg.get("goal_seeds", {})
        emp = r["employment_type"]
        gross_estimate = float(r["income_chf"] or 0.0) * 12.5 / 0.87
        goals = []

        def applies(when: dict) -> bool:
            return (when.get("min_age", 0) <= age <= when.get("max_age", 200)
                    and (not when.get("renter") or (renter and not r["owns_property"]))
                    and (not when.get("employment") or emp in when["employment"])
                    and (r["interest_travel"] or 0) >= when.get("interest_travel", 0))

        if (s := seeds.get("home")) and applies(s["when"]):
            canton_price = self.prices.get("by_canton", {}).get(client.canton or "", {})
            price = canton_price["median"] if canton_price.get("n", 0) >= 5 else self.prices.get("overall_median", 800_000)
            price = max(s["min_price"], min(price, s["max_income_multiple"] * gross_estimate)) if gross_estimate else price
            goals.append(GoalSpec(id=s["id"], type="home", label=s["label"].format(canton=client.canton or ""),
                                  target_date=add_months(as_of.replace(day=1), 12 * s["years"]),
                                  params={"price": round(price, -4), "canton": client.canton}, status="suggested", origin="data",
                                  note="You rent; typical price of homes owned by the bank's clients in your canton"))
        if (s := seeds.get("travel")) and applies(s["when"]):
            goals.append(GoalSpec(id=s["id"], type="target", label=s["label"], priority=2,
                                  target_date=add_months(as_of.replace(day=1), 12 * s["years"]), params={"amount": s["amount"]},
                                  status="suggested", origin="data", note="Travel is one of your interests"))
        if (s := seeds.get("retirement")) and applies(s["when"]):
            goals.append(GoalSpec(id=s["id"], type="retirement", label=s["label"], priority=3,
                                  params={"retirement_age": s["retirement_age"]}, status="suggested", origin="data",
                                  note="Everyone working needs this one"))
        return goals
