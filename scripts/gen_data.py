"""Synthetic bank data generator.

    python scripts/gen_data.py --persona lena --seed 1
    python scripts/gen_data.py --all

Reads scripts/personas/<persona>.yaml and writes data/synthetic/<persona>/:
  client.json    client master data, accounts (closing balances), positions, goals
  bookings.csv   a flattened camt.053-style export (semicolon, CdtDbtInd, BkTxCd, German texts)

The output deliberately contains mess the adapter and profile builder must survive:
German booking texts, TWINT P2P and merchant payments, cash withdrawals, lump credit-card
debits, a 13th salary, annual bills, delayed insurer reimbursements, internal transfers,
duplicate-looking bookings, an exact duplicate row, refunds and a missing export month.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
PERSONAS = Path(__file__).resolve().parent / "personas"
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
             "September", "Oktober", "November", "Dezember"]
COLUMNS = ["NtryRef", "AcctIBAN", "BookgDt", "ValDt", "Amt", "Ccy", "CdtDbtInd", "BkTxCd",
           "CdtrDbtrNm", "CdtrDbtrIBAN", "RmtInf", "AddtlNtryInf", "MCC"]


@dataclass
class Row:
    account: str
    d: date
    amount: float            # signed
    text: str
    counterparty: str = ""
    iban: str = ""
    code: str = ""
    mcc: str = ""
    rmt: str = ""
    value_days: int = 0


@dataclass
class Gen:
    spec: dict
    rng: np.random.Generator
    rows: list[Row] = field(default_factory=list)

    # ---------- helpers ----------
    @property
    def end(self) -> date:
        return self.spec["end_date"]

    @property
    def start(self) -> date:
        e = self.end
        y, m = divmod(e.year * 12 + e.month - 1 - (self.spec.get("months", 36) - 1), 12)
        return date(y, m + 1, 1)

    def months(self):
        d = self.start
        while d <= self.end:
            yield d
            y, m = divmod(d.year * 12 + d.month, 12)
            d = date(y, m + 1, 1)

    def acct(self, key: str | None) -> str:
        key = key or "private"
        for a in self.spec["accounts"]:
            if a.get("key", a["type"]) == key:
                return a["id"]
        raise KeyError(key)

    @staticmethod
    def business_day(d: date) -> date:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def day_in(self, month: date, day: int) -> date:
        last = (date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(days=1)).day
        return self.business_day(month.replace(day=min(day, last)))

    def active(self, item: dict, d: date) -> bool:
        s, e = item.get("start"), item.get("end")
        return (s is None or d >= s) and (e is None or d <= e)

    def fmt(self, template: str, month: date, **kw) -> str:
        return template.format(month_name=MONTHS_DE[month.month - 1], month=f"{month.month:02d}",
                               year=month.year, **kw)

    def add(self, **kw):
        if kw["d"] <= self.end:
            self.rows.append(Row(**kw))

    def amount(self, spec: dict) -> float:
        if "median" in spec:
            v = spec["median"] * math.exp(spec.get("sigma", 0.5) * self.rng.standard_normal())
        else:
            v = spec["amount"] * (1 + spec.get("jitter", 0.0) * self.rng.uniform(-1, 1))
        return round(v * 20) / 20 if spec.get("round05", True) else round(v, 2)

    # ---------- generators ----------
    def income(self):
        for inc in self.spec.get("income", []):
            base = inc["net_monthly"]
            for m in self.months():
                if not self.active(inc, m):
                    continue
                # net_monthly is today's salary; earlier months are lower by one raise per year
                rm = inc.get("raise_month", 1)
                raises_since = sum(1 for y in range(m.year, self.end.year + 1) if m < date(y, rm, 1) <= self.end)
                amt = base / (1 + inc.get("raise_pct", 0.0)) ** raises_since
                if inc.get("volatility"):
                    amt *= max(0.0, 1 + inc["volatility"] * self.rng.standard_normal())
                d = self.day_in(m, inc.get("day", 25))
                txt = self.fmt(inc.get("text", "Gutschrift Lohn {month_name} {year}"), m)
                self.add(account=self.acct(inc.get("account")), d=d, amount=round(amt, 2), text=txt,
                         counterparty=inc["counterparty"], iban=inc.get("iban", ""),
                         code=inc.get("code", "PMNT-RCDT-SALA"), rmt=inc.get("rmt", ""))
                if inc.get("thirteenth_month") == m.month:
                    self.add(account=self.acct(inc.get("account")), d=d, amount=round(amt, 2),
                             text=self.fmt("Gutschrift 13. Monatslohn {year}", m),
                             counterparty=inc["counterparty"], iban=inc.get("iban", ""),
                             code=inc.get("code", "PMNT-RCDT-SALA"))

    def recurring(self):
        for item in self.spec.get("recurring", []):
            every = item.get("every", "monthly")
            months = {"monthly": list(range(1, 13)), "quarterly": item.get("months", [1, 4, 7, 10]),
                      "yearly": [item.get("month", 1)], "semiannual": item.get("months", [1, 7])}[every]
            for m in self.months():
                if m.month not in months or not self.active(item, m):
                    continue
                amt = -abs(self.amount(item)) if item.get("sign", -1) < 0 else abs(self.amount(item))
                self.add(account=self.acct(item.get("account")), d=self.day_in(m, item.get("day", 1)),
                         amount=amt, text=self.fmt(item["text"], m), counterparty=item.get("counterparty", ""),
                         iban=item.get("iban", ""), code=item.get("code", "PMNT-ICDT-STDO"),
                         mcc=str(item.get("mcc", "")), rmt=self.fmt(item.get("rmt", ""), m))

    def variable(self):
        for item in self.spec.get("variable", []):
            for m in self.months():
                if not self.active(item, m):
                    continue
                if item.get("active_months") and m.month not in item["active_months"]:
                    continue
                n = self.rng.poisson(item["per_month"] * item.get("seasonality", {}).get(m.month, 1.0))
                for _ in range(n):
                    merchant = item["merchants"][self.rng.integers(len(item["merchants"]))]
                    d = self.business_day(m + timedelta(days=int(self.rng.integers(0, 28))))
                    city = item.get("cities", ["Zürich"])[self.rng.integers(len(item.get("cities", ["Zürich"])))]
                    txt = item.get("text", "Einkauf {merchant} {city} Karte xxxx 4821").format(merchant=merchant, city=city)
                    amt = abs(self.amount(item)) * (1 if item.get("sign", -1) > 0 else -1)
                    self.add(account=self.acct(item.get("account")), d=d, amount=amt,
                             text=txt, counterparty=merchant if item.get("counterparty_field", True) else "",
                             code=item.get("code", "PMNT-CCRD-POSD" if amt < 0 else "PMNT-RCDT-DMCT"), mcc=str(item.get("mcc", "")))

    def twint_p2p(self):
        t = self.spec.get("twint_p2p")
        if not t:
            return
        for m in self.months():
            for _ in range(self.rng.poisson(t["per_month"])):
                name = t["names"][self.rng.integers(len(t["names"]))]
                d = self.business_day(m + timedelta(days=int(self.rng.integers(0, 28))))
                incoming = self.rng.uniform() < t.get("incoming_share", 0.25)
                amt = self.amount(t)
                self.add(account=self.acct(None), d=d, amount=amt if incoming else -amt,
                         text=("TWINT *Empfangen von " if incoming else "TWINT *Sende an ") + name,
                         counterparty="", code="PMNT-RCDT-ESCT" if incoming else "PMNT-ICDT-ESCT")

    def cash(self):
        c = self.spec.get("cash")
        if not c:
            return
        for m in self.months():
            for _ in range(self.rng.poisson(c["per_month"])):
                atm = c["atms"][self.rng.integers(len(c["atms"]))]
                d = self.business_day(m + timedelta(days=int(self.rng.integers(0, 28))))
                amt = max(20, round(self.amount(c) / 20) * 20)
                self.add(account=self.acct(None), d=d, amount=-amt, text=f"Bargeldbezug {atm} Karte xxxx 4821",
                         code="PMNT-CCRD-CWDL", mcc="6011")

    def credit_card(self):
        cc = self.spec.get("credit_card")
        if not cc:
            return
        totals: dict[date, float] = {}
        for item in cc["items"]:
            for m in self.months():
                if "schedule" in item:   # planned spending, e.g. holidays: {month: amount}
                    amt = item["schedule"].get(m.month, 0)
                    totals[m] = totals.get(m, 0.0) + abs(self.amount({"amount": amt, "jitter": item.get("jitter", 0.2)})) if amt else totals.get(m, 0.0)
                    continue
                n = self.rng.poisson(item["per_month"] * item.get("seasonality", {}).get(m.month, 1.0))
                totals[m] = totals.get(m, 0.0) + sum(abs(self.amount(item)) for _ in range(n))
        for m, tot in totals.items():
            if tot < 1:
                continue
            nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            self.add(account=self.acct(None), d=self.day_in(nxt, cc.get("day", 20)), amount=-round(tot, 2),
                     text=f"Lastschrift {cc['issuer']} Monatsrechnung {m.month:02d}/{m.year}",
                     counterparty=cc["issuer"], code="PMNT-IDDT-ESDD")

    def health(self):
        h = self.spec.get("health_bills")
        if not h:
            return
        spent: dict[int, float] = {}
        for m in self.months():
            for _ in range(self.rng.poisson(h["per_year"] / 12)):
                doc = h["providers"][self.rng.integers(len(h["providers"]))]
                d = self.business_day(m + timedelta(days=int(self.rng.integers(0, 28))))
                amt = self.amount(h)
                self.add(account=self.acct(None), d=d, amount=-amt, text=f"Zahlung Rechnung {doc}",
                         counterparty=doc, code="PMNT-ICDT-DMCT", rmt="Honorarrechnung")
                before = spent.get(d.year, 0.0)
                spent[d.year] = before + amt
                covered = max(0.0, spent[d.year] - h["deductible"]) - max(0.0, before - h["deductible"])
                if covered > 0:
                    self.add(account=self.acct(None), d=self.business_day(d + timedelta(days=h.get("delay_days", 45))),
                             amount=round(covered * 0.9, 2), text=f"Gutschrift {h['insurer']} Leistungsabrechnung",
                             counterparty=h["insurer"], code="PMNT-RCDT-DMCT")

    def internal(self):
        for t in self.spec.get("internal_transfers", []):
            to_acct = self.acct(t["to"])
            from_acct = self.acct(t.get("from", "private"))
            for m in self.months():
                if not self.active(t, m):
                    continue
                d = self.day_in(m, t.get("day", 27))
                txt = t.get("text", "Übertrag Sparkonto")
                self.add(account=from_acct, d=d, amount=-t["amount"], text=txt, iban=to_acct, code="PMNT-ICDT-BOOK")
                self.add(account=to_acct, d=d, amount=t["amount"], text=txt, iban=from_acct, code="PMNT-RCDT-BOOK")

    def interest(self):
        for a in self.spec["accounts"]:
            if a.get("interest_rate"):
                for m in self.months():
                    if m.month == 12:
                        self.add(account=a["id"], d=date(m.year, 12, 31) if date(m.year, 12, 31) <= self.end else self.end,
                                 amount=round(a.get("closing_balance", 0) * a["interest_rate"], 2),
                                 text="Zinsgutschrift", code="ACMT-MDOP-INTR")

    def one_offs(self):
        for o in self.spec.get("one_offs", []):
            self.add(account=self.acct(o.get("account")), d=o["date"], amount=o["amount"], text=o["text"],
                     counterparty=o.get("counterparty", ""), code=o.get("code", "PMNT-CCRD-POSD"),
                     mcc=str(o.get("mcc", "")))

    def mess(self):
        mess = self.spec.get("messiness", {})
        card = [r for r in self.rows if r.code == "PMNT-CCRD-POSD"]
        for r in self.rng.choice(card, size=min(mess.get("duplicate_looking", 0), len(card)), replace=False):
            self.rows.append(Row(**{**r.__dict__, "text": r.text}))
        for ref in mess.get("refunds", []):
            self.add(account=self.acct(None), d=ref["date"], amount=abs(ref["amount"]),
                     text=f"Gutschrift {ref['merchant']} Retoure", counterparty=ref["merchant"], code="PMNT-RCDT-ESCT")
        if mess.get("missing_month"):
            y, mo = map(int, mess["missing_month"].split("-"))
            self.rows = [r for r in self.rows if not (r.account == self.acct(None) and r.d.year == y and r.d.month == mo)]

    def run(self):
        for step in (self.income, self.recurring, self.variable, self.twint_p2p, self.cash, self.credit_card,
                     self.health, self.internal, self.interest, self.one_offs, self.mess):
            step()
        self.rows.sort(key=lambda r: (r.d, r.account, r.amount))
        return self.rows


def balances(spec: dict, rows: list[Row]) -> dict[str, float]:
    """Closing balances per account: the persona's target, lifted so the running balance never dips below a floor."""
    out = {}
    for a in spec["accounts"]:
        own = [r for r in rows if r.account == a["id"]]
        total = sum(r.amount for r in own)
        opening = a.get("closing_balance", 0.0) - total
        running, low = opening, opening
        for r in own:
            running += r.amount
            low = min(low, running)
        floor = a.get("min_balance", 300.0)
        lift = max(0.0, floor - low)
        out[a["id"]] = round(opening + lift + total, 2)
    return out


def write(spec: dict, rows: list[Row], out_dir: Path, rng: np.random.Generator):
    out_dir.mkdir(parents=True, exist_ok=True)
    closing = balances(spec, rows)
    client = dict(spec["client"])
    client["goals"] = spec.get("goals", [])
    doc = {
        "as_of": spec["end_date"].isoformat(),
        "client": client,
        "accounts": [{"id": a["id"], "iban": a["id"], "client_id": client["id"], "type": a["type"],
                      "name": a.get("name"), "currency": "CHF",
                      "balance": closing.get(a["id"], a.get("closing_balance", 0.0))}
                     for a in spec["accounts"]],
        "positions": spec.get("positions", []),
    }
    (out_dir / "client.json").write_text(json.dumps(doc, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    with (out_dir / "bookings.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(COLUMNS)
        for i, r in enumerate(rows):
            vd = r.d + timedelta(days=r.value_days)
            w.writerow([f"{spec['id'].upper()}-{i:06d}", r.account, r.d.isoformat(), vd.isoformat(),
                        f"{abs(r.amount):.2f}", "CHF", "CRDT" if r.amount > 0 else "DBIT", r.code,
                        r.counterparty, r.iban, r.rmt, r.text, r.mcc])
        dup = spec.get("messiness", {}).get("exact_duplicate_rows", 0)
        for j in rng.choice(len(rows), size=min(dup, len(rows)), replace=False):
            r = rows[j]
            w.writerow([f"{spec['id'].upper()}-{j:06d}", r.account, r.d.isoformat(), r.d.isoformat(),
                        f"{abs(r.amount):.2f}", "CHF", "CRDT" if r.amount > 0 else "DBIT", r.code,
                        r.counterparty, r.iban, r.rmt, r.text, r.mcc])
    return closing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", action="append")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default=str(ROOT / "data" / "synthetic"))
    args = ap.parse_args()
    names = sorted(p.stem for p in PERSONAS.glob("*.yaml")) if args.all or not args.persona else args.persona
    for name in names:
        spec = yaml.safe_load((PERSONAS / f"{name}.yaml").read_text(encoding="utf-8"))
        rng = np.random.default_rng(args.seed)
        rows = Gen(spec, rng).run()
        closing = write(spec, rows, Path(args.out) / spec["id"], rng)
        print(f"{spec['id']}: {len(rows)} bookings, closing balances {closing}")


if __name__ == "__main__":
    main()
