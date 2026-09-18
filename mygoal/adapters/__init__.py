"""Adapters turn raw data into the canonical model (mygoal/model/canonical.py).

Tomorrow's real data should only need one of:
  1. a new column mapping YAML in adapters/mappings/ (same layout, different columns), or
  2. a new adapter module registered with @register_adapter("name") (different layout).
Then set `data.source` in config/app.yaml or MYGOAL_DATA_SOURCE.
"""
from .base import ADAPTERS, ClientSummary, DataSource, get_source, register_adapter

__all__ = ["ADAPTERS", "ClientSummary", "DataSource", "get_source", "register_adapter"]
