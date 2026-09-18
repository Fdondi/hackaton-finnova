"""Placeholder for the organisers' data. Fill in on the day (plan §12 checklist).

Recipe:
  1. `python scripts/inspect_data.py <file>` to see delimiter, columns, date and number formats.
  2. If it's one table of bookings per client (or with a client column): copy
     mappings/camt_flat.yaml to mappings/realdata.yaml, fix the column names, and use this adapter.
  3. If client master data lives elsewhere (or not at all), build Client/Account objects below;
     unknown fields can stay None: the profile builder and UI fall back to defaults and ask.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path

from ..config import Config, resolve_path
from ..model import Account, Client, Dataset
from .base import ClientSummary, register_adapter
from .tabular import load_mapping, read_bookings


@register_adapter("realdata")
class RealDataSource:
    def __init__(self, cfg: Config):
        self.path = resolve_path(cfg.get_path("app.data.dir", "data/real"))
        self.mapping = load_mapping(cfg.get_path("app.data.mapping", "realdata"))
        self.client_column = self.mapping.get("client_column")   # None: one file == one client
        self._cache: dict[str, Dataset] | None = None

    def _files(self) -> list[Path]:
        if self.path.is_file():
            return [self.path]
        return sorted(p for p in self.path.iterdir() if p.suffix.lower() in {".csv", ".xlsx", ".json", ".txt"})

    def _load_all(self) -> dict[str, Dataset]:
        if self._cache is not None:
            return self._cache
        by_client: dict[str, list] = defaultdict(list)
        for f in self._files():
            bookings, _ = read_bookings(f, self.mapping)
            for b in bookings:
                cid = str(b.extra.get(self.client_column, f.stem)) if self.client_column else f.stem
                by_client[cid].append(b)
        out = {}
        for cid, bookings in by_client.items():
            accounts = sorted({b.account_id for b in bookings})
            out[cid] = Dataset(
                client=Client(id=cid, name=cid),
                accounts=[Account(id=a, client_id=cid, type="private") for a in accounts],  # TODO balances
                bookings=bookings,
                as_of=max(b.booking_date for b in bookings) if bookings else date.today(),
                source="realdata",
            )
        self._cache = out
        return out

    def list_clients(self) -> list[ClientSummary]:
        return [ClientSummary(id=k, name=v.client.name, n_bookings=len(v.bookings)) for k, v in self._load_all().items()]

    def load(self, client_id: str) -> Dataset:
        return self._load_all()[client_id]
