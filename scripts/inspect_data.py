"""First look at an unknown data file (plan §12 checklist). Prints what an adapter mapping needs to know.

    python scripts/inspect_data.py path/to/export.csv [--sheet 0]
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import pandas as pd

DATE_PATTERNS = {r"^\d{4}-\d{2}-\d{2}": "%Y-%m-%d", r"^\d{2}\.\d{2}\.\d{4}": "%d.%m.%Y", r"^\d{2}/\d{2}/\d{4}": "%d/%m/%Y"}


def sniff(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()[:20000]
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        delim = csv.Sniffer().sniff(text.split("\n", 5)[1] if "\n" in text else text, delimiters=";,\t|").delimiter
    except csv.Error:
        delim = ";"
    return enc, delim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--sheet", default=0)
    args = ap.parse_args()
    path = Path(args.path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, sheet_name=args.sheet, dtype=str)
        print(f"Excel, sheet {args.sheet}")
    elif path.suffix.lower() in (".json", ".jsonl"):
        df = pd.read_json(path, lines=path.suffix == ".jsonl", dtype=str)
    else:
        enc, delim = sniff(path)
        print(f"encoding={enc!r} delimiter={delim!r}")
        df = pd.read_csv(path, sep=delim, encoding=enc, dtype=str, keep_default_na=False, engine="python")
    print(f"{len(df)} rows, {len(df.columns)} columns\n")
    for col in df.columns:
        vals = df[col].astype(str)
        non_empty = vals[vals.str.strip() != ""]
        sample = non_empty.head(3).tolist()
        hint = ""
        if len(non_empty):
            v = non_empty.iloc[0]
            for pat, fmt in DATE_PATTERNS.items():
                if re.match(pat, v):
                    hint = f"date? {fmt}"
            if re.fullmatch(r"-?[\d'’.,]+-?", v):
                hint = "number? decimal=',' " if re.search(r",\d{2}$", v) else "number?"
            if re.fullmatch(r"(CRDT|DBIT|C|D|\+|-)", v):
                hint = "sign indicator?"
            if re.fullmatch(r"CH\d{2}[\dA-Z]{17}", v.replace(" ", "")):
                hint = "IBAN?"
        print(f"- {col!r:30} filled {len(non_empty) / max(len(df), 1):5.0%}  unique {non_empty.nunique():6}  {hint:22} e.g. {sample}")
    text_cols = sorted(df.columns, key=lambda c: -df[c].astype(str).str.len().mean())
    if text_cols:
        words = " ".join(df[text_cols[0]].astype(str).head(500)).lower()
        de = sum(words.count(w) for w in (" einkauf", "zahlung", "gutschrift", "lastschrift", "twint"))
        print(f"\nLongest text column {text_cols[0]!r}: German booking words found {de} times")
    print("\nNext: copy mygoal/adapters/mappings/camt_flat.yaml, fill the column names, set app.data.source=realdata.")


if __name__ == "__main__":
    main()
