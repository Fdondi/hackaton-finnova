"""Tiny plugin registries.

Adding a module = writing a file with a decorator. Nothing else needs editing:
`load_plugins()` imports every module in the plugin packages, plus any extra
packages/modules listed in the MYGOAL_PLUGINS env var (comma-separated).
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Callable, Generic, Iterator, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, name: str):
        self.name = name
        self._items: dict[str, T] = {}

    def register(self, key: str, item: T, *, replace: bool = True) -> T:
        if key in self._items and not replace:
            raise KeyError(f"{self.name}: '{key}' already registered")
        self._items[key] = item
        return item

    def decorator(self, key: str) -> Callable[[T], T]:
        def wrap(item: T) -> T:
            return self.register(key, item)
        return wrap

    def get(self, key: str) -> T:
        try:
            return self._items[key]
        except KeyError:
            raise KeyError(f"{self.name}: unknown '{key}'. Known: {sorted(self._items)}") from None

    def __contains__(self, key: str) -> bool:
        return key in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def items(self):
        return self._items.items()

    def values(self):
        return self._items.values()


PLUGIN_PACKAGES = [
    "mygoal.adapters",
    "mygoal.goals",
    "mygoal.levers",
    "mygoal.specialists",
    "mygoal.explain",
    "mygoal.agent",
]

_loaded = False


def load_plugins(force: bool = False) -> None:
    global _loaded
    if _loaded and not force:
        return
    extra = [p.strip() for p in os.environ.get("MYGOAL_PLUGINS", "").split(",") if p.strip()]
    for pkg_name in PLUGIN_PACKAGES + extra:
        pkg = importlib.import_module(pkg_name)
        if hasattr(pkg, "__path__"):
            for mod in pkgutil.walk_packages(pkg.__path__, prefix=pkg_name + "."):
                importlib.import_module(mod.name)
    _loaded = True
