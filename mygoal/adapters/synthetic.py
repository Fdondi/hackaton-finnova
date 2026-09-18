"""Folder-per-client source: <dir>/<client_id>/client.json + bookings.csv (camt_flat mapping)."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ..config import Config, resolve_path
from ..model import Account, Client, Dataset, Position
from .base import ClientSummary, register_adapter
from .tabular import read_bookings


@register_adapter("synthetic")
class FolderSource:
    mapping = "camt_flat"

    def __init__(self, cfg: Config):
        self.dir = resolve_path(cfg.get_path("app.data.dir", "data/synthetic"))

    def _folders(self) -> list[Path]:
        return sorted(p for p in self.dir.iterdir() if (p / "client.json").exists()) if self.dir.exists() else []

    def list_clients(self) -> list[ClientSummary]:
        out = []
        for p in self._folders():
            c = json.loads((p / "client.json").read_text(encoding="utf-8"))["client"]
            out.append(ClientSummary(id=c["id"], name=c.get("name"), canton=c.get("canton"), birth_year=c.get("birth_year")))
        return out

    def load(self, client_id: str) -> Dataset:
        folder = self.dir / client_id
        doc = json.loads((folder / "client.json").read_text(encoding="utf-8"))
        client = Client.model_validate(doc["client"])
        accounts = [Account.model_validate({**a, "client_id": client.id}) for a in doc.get("accounts", [])]
        bookings, warnings = read_bookings(folder / "bookings.csv", self.mapping)
        as_of = date.fromisoformat(doc["as_of"]) if doc.get("as_of") else max(b.booking_date for b in bookings)
        client.extra.setdefault("adapter_warnings", warnings)
        return Dataset(client=client, accounts=accounts, bookings=bookings,
                       positions=[Position.model_validate(p) for p in doc.get("positions", [])],
                       as_of=as_of, source="synthetic")
