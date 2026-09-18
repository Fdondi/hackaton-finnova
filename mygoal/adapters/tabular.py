"""Mapping-driven reader for tabular booking exports (CSV, Excel, JSON lines/records).

The mapping YAML says which raw column feeds which canonical field, how amounts are signed,
and how numbers and dates are written. See mappings/camt_flat.yaml for the annotated example.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..model import Booking

MAPPINGS_DIR = Path(__file__).parent / "mappings"
CANONICAL_FIELDS = ["id", "account_id", "booking_date", "value_date", "amount", "currency", "text",
                    "counterparty", "counterparty_iban", "mcc", "bank_tx_code", "bank_category"]


def load_mapping(name_or_path: str | Path) -> dict:
    p = Path(name_or_path)
    if not p.exists():
        p = MAPPINGS_DIR / f"{name_or_path}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def read_table(path: Path, m: dict) -> pd.DataFrame:
    fmt = m.get("format") or path.suffix.lstrip(".").lower()
    if fmt in ("csv", "txt", "tsv"):
        return pd.read_csv(path, sep=m.get("delimiter", ";"), encoding=m.get("encoding", "utf-8"), dtype=str,
                           keep_default_na=False, skiprows=m.get("skip_rows", 0), engine="python")
    if fmt in ("xlsx", "xls", "excel"):
        return pd.read_excel(path, sheet_name=m.get("sheet", 0), dtype=str, skiprows=m.get("skip_rows", 0)).fillna("")
    if fmt in ("json", "jsonl"):
        return pd.read_json(path, lines=fmt == "jsonl", dtype=str).fillna("")
    if fmt == "parquet":
        return pd.read_parquet(path).astype(str)
    raise ValueError(f"unsupported format {fmt}")


def parse_amount(raw: Any, decimal: str = ".", thousands: str | None = None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("−", "-").replace("CHF", "").replace(" ", "").replace(" ", "")
    for t in filter(None, [thousands, "'", "’"]):
        s = s.replace(t, "")
    negative = s.endswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-+") if negative else s
    if decimal == ",":
        s = s.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if negative else v


def parse_date(raw: Any, formats: list[str]) -> date | None:
    s = str(raw).strip()
    if not s:
        return None
    for f in formats:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, dayfirst=not s[:4].isdigit()).date()
    except (ValueError, TypeError):
        return None


def _field(row: dict, spec: Any) -> str | None:
    if spec is None:
        return None
    if isinstance(spec, dict) and "const" in spec:
        return str(spec["const"])
    if isinstance(spec, list):
        parts = [str(row.get(c, "")).strip() for c in spec]
        return " | ".join(p for p in parts if p) or None
    v = str(row.get(spec, "")).strip()
    return v or None


def rows_to_bookings(df: pd.DataFrame, m: dict, default_account: str = "main") -> tuple[list[Booking], list[str]]:
    cols = m["columns"]
    sign = m.get("sign", {"mode": "signed"})
    decimal, thousands = m.get("decimal", "."), m.get("thousands")
    formats = m.get("date_formats") or [m.get("date_format", "%Y-%m-%d")]
    used = {c for spec in cols.values() for c in ([spec] if isinstance(spec, str) else spec if isinstance(spec, list) else [])}
    used |= {sign.get("column"), sign.get("debit_column"), sign.get("credit_column")}
    warnings: list[str] = []
    out: list[Booking] = []
    seen_ids: set[str] = set()
    dupes = 0
    for i, row in enumerate(df.to_dict(orient="records")):
        mode = sign.get("mode", "signed")
        if mode == "split":
            debit = parse_amount(row.get(sign["debit_column"]), decimal, thousands) or 0.0
            credit = parse_amount(row.get(sign["credit_column"]), decimal, thousands) or 0.0
            amount = abs(credit) - abs(debit)
        else:
            amount = parse_amount(_field(row, cols.get("amount")), decimal, thousands)
            if amount is None:
                warnings.append(f"row {i}: unreadable amount, skipped")
                continue
            if mode == "indicator":
                ind = str(row.get(sign["column"], "")).strip().upper()
                if ind in [v.upper() for v in sign.get("debit_values", ["DBIT", "D"])]:
                    amount = -abs(amount)
                elif ind in [v.upper() for v in sign.get("credit_values", ["CRDT", "C"])]:
                    amount = abs(amount)
            elif sign.get("invert"):
                amount = -amount
        bdate = parse_date(_field(row, cols.get("booking_date")), formats)
        if bdate is None:
            warnings.append(f"row {i}: unreadable booking date, skipped")
            continue
        text = _field(row, cols.get("text")) or ""
        bid = _field(row, cols.get("id"))
        if bid is None:  # synthesize a stable id; identical rows keep distinct ids (they may be legit)
            bid = hashlib.sha1(f"{i}|{sorted(row.items())}".encode()).hexdigest()[:16]
        elif bid in seen_ids:
            dupes += 1
            continue
        seen_ids.add(bid)
        mcc = _field(row, cols.get("mcc"))
        out.append(Booking(
            id=bid,
            account_id=_field(row, cols.get("account_id")) or default_account,
            booking_date=bdate,
            value_date=parse_date(_field(row, cols.get("value_date")), formats),
            amount=round(amount, 2),
            currency=_field(row, cols.get("currency")) or "CHF",
            text=text,
            counterparty=_field(row, cols.get("counterparty")),
            counterparty_iban=(_field(row, cols.get("counterparty_iban")) or "").replace(" ", "") or None,
            mcc=mcc.split(".")[0] if mcc else None,
            bank_tx_code=_field(row, cols.get("bank_tx_code")),
            bank_category=_field(row, cols.get("bank_category")),
            extra={k: v for k, v in row.items() if k not in used and str(v).strip()},
        ))
    if dupes:
        warnings.append(f"{dupes} exact duplicate rows (same booking id) dropped")
    return out, warnings


def read_bookings(path: str | Path, mapping: str | Path | dict) -> tuple[list[Booking], list[str]]:
    m = mapping if isinstance(mapping, dict) else load_mapping(mapping)
    df = read_table(Path(path), m)
    missing = [c for c in _required_columns(m) if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: columns {missing} not found. Available: {list(df.columns)}")
    return rows_to_bookings(df, m)


def _required_columns(m: dict) -> list[str]:
    cols = m["columns"]
    req = []
    for f in ("booking_date", "amount"):
        spec = cols.get(f)
        if isinstance(spec, str):
            req.append(spec)
    return req


_WS = re.compile(r"\s+")
