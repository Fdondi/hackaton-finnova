"""External services behind interfaces (insurer quotes, market data, ...). Mocks tonight, real integrations later.

Register a factory with @service("name"); pick an implementation with env MYGOAL_SERVICE_<NAME>=<impl>.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from .config import Config
from .registry import Registry

SERVICES: Registry[dict[str, Callable[[Config], Any]]] = Registry("services")


def service(name: str, impl: str = "mock"):
    def wrap(factory):
        impls = SERVICES._items.setdefault(name, {})
        impls[impl] = factory
        return factory
    return wrap


def build_services(cfg: Config) -> dict[str, Any]:
    out = {}
    for name, impls in SERVICES.items():
        choice = os.environ.get(f"MYGOAL_SERVICE_{name.upper()}", "mock")
        out[name] = impls.get(choice, next(iter(impls.values())))(cfg)
    return out
