"""Integrations: other companies' APIs that speak the scenario format, and how we find out a new one is compatible.

config/partners.yaml lists the known ones (`activated: true` = the client connected it before, so it is listed right
away). A connector gets the request (contract.request: a few readable fields) and returns the reply. Any API that
speaks the format over HTTP uses the `http` connector; anything else is a function registered with @connector("name").
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urljoin, urlparse

import httpx

from ..config import Config
from ..registry import Registry
from .contract import FORMAT, WELL_KNOWN

if TYPE_CHECKING:
    from ..service import PlanningService

Connector = Callable[[dict[str, Any], dict[str, Any], "PlanningService"], dict[str, Any]]
CONNECTORS: Registry[Connector] = Registry("partner connectors")
MAX_BYTES = 256_000


def connector(name: str) -> Callable[[Connector], Connector]:
    return CONNECTORS.decorator(name)


def partners(cfg: Config) -> list[dict[str, Any]]:
    return list(cfg.get_path("partners.partners", []) or [])


def partner(cfg: Config, partner_id: str) -> dict[str, Any]:
    for p in partners(cfg):
        if p["id"] == partner_id:
            return p
    raise KeyError(f"unknown partner {partner_id}")


def get_json(url: str, timeout: float = 5) -> Any:
    r = httpx.get(url, timeout=timeout, follow_redirects=False)
    r.raise_for_status()
    if len(r.content) > MAX_BYTES:
        raise ValueError("answer too large")
    return r.json()


def post_json(url: str, body: dict[str, Any], timeout: float = 30) -> Any:
    r = httpx.post(url, json=body, timeout=timeout, follow_redirects=False)
    r.raise_for_status()
    if len(r.content) > MAX_BYTES:
        raise ValueError("answer too large")
    return r.json()


def discover(url: str) -> tuple[dict[str, Any], str]:
    """A compatible API's description at the address, or at /.well-known/mygoal-scenarios on the same host.
    Returns (description, endpoint to POST to); ValueError when there is none."""
    url = url.strip()
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("Enter a web address starting with https:// (or http://)")
    tried = [url] + ([f"{u.scheme}://{u.netloc}{WELL_KNOWN}"] if u.path != WELL_KNOWN else [])
    for candidate in tried:
        try:
            d = get_json(candidate)
        except (httpx.HTTPError, ValueError):
            continue
        if isinstance(d, dict) and d.get("format") == FORMAT and str(d.get("name") or "").strip():
            return d, urljoin(candidate, str(d.get("endpoint") or ""))
    raise ValueError(f"No {FORMAT} description found at {' or '.join(tried)}")


@connector("http")
def http(req: dict[str, Any], p: dict[str, Any], svc: "PlanningService") -> dict[str, Any]:
    """A company's API that speaks the format: POST the request, get the reply back."""
    return post_json(p["url"], req, float(p.get("timeout", 30)))
