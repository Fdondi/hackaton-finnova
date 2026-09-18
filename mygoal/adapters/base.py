from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from ..config import Config
from ..model import Dataset
from ..registry import Registry, load_plugins


class ClientSummary(BaseModel):
    id: str
    name: str | None = None
    canton: str | None = None
    birth_year: int | None = None
    n_bookings: int | None = None


class DataSource(Protocol):
    def list_clients(self) -> list[ClientSummary]: ...
    def load(self, client_id: str) -> Dataset: ...


ADAPTERS: Registry[type] = Registry("adapters")


def register_adapter(name: str):
    return ADAPTERS.decorator(name)


def get_source(cfg: Config) -> DataSource:
    load_plugins()
    name = cfg.get_path("app.data.source", "synthetic")
    return ADAPTERS.get(name)(cfg)
