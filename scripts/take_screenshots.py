"""Capture the README screenshots from a running app (headless Chromium via Playwright).

    uv run --with playwright python scripts/take_screenshots.py [--base http://127.0.0.1:8080] [--client 0] [--only 03,05]

The client is reset first (POST /api/clients/{id}/reset). Use 127.0.0.1, not localhost: podman's port forward
can reset the IPv6 connection. Every shot is cropped to the part of the page that shows its feature.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Callable

from playwright.sync_api import Locator, Page, sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
W, H = 1440, 900
# on top of the AI's suggestions: two goals that are hard to reach on this income
HARD_GOALS = ["a sailing boat for CHF 90'000 in 5 years", "a six-month sabbatical for CHF 40'000 in 3 years"]
COLUMN = (208, 1232)   # the main page's content column


def api(base: str, path: str, method: str = "GET"):
    req = urllib.request.Request(f"{base}/api{path}", method=method, data=b"" if method == "POST" else None)
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return json.loads(body) if body else None


def settle(pg: Page, ms: int = 1500) -> None:
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(ms)


def top(loc: Locator, pad: int = 0) -> Callable[[], float]:
    return lambda: loc.first.bounding_box()["y"] - pad


def bottom(loc: Locator, pad: int = 0) -> Callable[[], float]:
    return lambda: (lambda b: b["y"] + b["height"])(loc.first.bounding_box()) + pad


def shot(pg: Page, name: str, y0: Callable[[], float], y1: Callable[[], float], x: tuple[int, int] = COLUMN) -> None:
    """Grow the viewport to the whole page (so nothing is scrolled and the sticky header stays on top), then save only
    the strip between two elements."""
    OUT.mkdir(parents=True, exist_ok=True)
    pg.set_viewport_size({"width": W, "height": max(H, pg.evaluate("document.documentElement.scrollHeight"))})
    pg.wait_for_timeout(500)
    top_y, bottom_y = max(0, y0()), y1()
    pg.screenshot(path=str(OUT / f"{name}.png"),
                  clip={"x": x[0], "y": top_y, "width": x[1] - x[0], "height": bottom_y - top_y})
    pg.set_viewport_size({"width": W, "height": H})
    print("saved", name)


def confirmed_goals(base: str, client_id: str) -> int:
    return sum(g["status"] == "confirmed" for g in api(base, f"/clients/{client_id}/goals"))


def add_goal(pg: Page, base: str, client_id: str, text: str) -> None:
    """Type a goal in the box; it counts once the server has it confirmed (the AI may take a while)."""
    n = confirmed_goals(base, client_id)
    pg.get_by_placeholder("I want to buy a car").fill(text)
    pg.get_by_role("button", name="Add", exact=True).click()
    for _ in range(90):
        if confirmed_goals(base, client_id) > n:
            break
        pg.wait_for_timeout(1000)
    else:
        raise RuntimeError(f"goal not added: {text!r} (the AI may have asked a question)")
    settle(pg, 1000)


def pick_client(pg: Page, name: str) -> None:
    """The picker is a type-to-search datalist input: an exact name selects the client."""
    pg.wait_for_selector("input[list=client-list]")
    pg.fill("input[list=client-list]", name)
    settle(pg, 2000)


def run(base: str, only: set[str], client: int) -> None:
    want = lambda n: not only or n[:2] in only
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": W, "height": H}).new_page()
        who = api(base, "/clients")[client]
        api(base, f"/clients/{who['id']}/reset", "POST")   # every run starts from the data, whatever earlier runs did
        pg.goto(base)
        if client:
            pick_client(pg, who["name"])
        pg.wait_for_selector("text=Tell us your financial goal")
        settle(pg, 2500)

        # 1. goals: accept the AI's suggestions, add goals of our own
        for _ in range(4):
            pg.get_by_role("button", name="Confirm").first.click()
            pg.wait_for_timeout(800)
        for text in HARD_GOALS:
            add_goal(pg, base, who["id"], text)
        if want("01-goals"):
            shot(pg, "01-goals", top(pg.get_by_text("Tell us your financial goal"), 50),
                 bottom(pg.get_by_role("button", name="Show me my plan"), 20), x=(140, 1300))

        # 2. every goal on one chart, with the options switched on
        pg.get_by_role("button", name="Show me my plan").click()
        pg.wait_for_selector(".recharts-surface")
        settle(pg, 4000)
        chart_top = top(pg.get_by_text("Your goals over time"), 32)
        pg.get_by_role("button", name="Activate all recommended").click()
        settle(pg, 3000)
        if want("02-main"):
            shot(pg, "02-main", chart_top, top(pg.get_by_text("What would help:"), 30))

        # 3. a what-if, next to the recommended options
        pg.get_by_placeholder("What if I").fill("I put CHF 20'000 into crypto next year, once, nothing monthly")
        pg.get_by_role("button", name="Try it").click()
        accept = pg.get_by_role("button", name="Accept this action")
        ask = pg.get_by_text("Suggest a value")
        accept.or_(ask).first.wait_for(timeout=120000)   # the LLM answers in its own time...
        if ask.count():                                   # ...and sometimes asks one question first
            pg.get_by_placeholder("CHF/month").fill("0")
            pg.get_by_role("button", name="OK", exact=True).click()
        accept.wait_for(timeout=120000)
        settle(pg, 3000)
        if want("03-actions"):
            shot(pg, "03-actions", top(pg.get_by_text("What would help:"), 30), bottom(pg.get_by_text(re.compile(r"^\d+ steps?$")), 4))

        # 4. borrowing to invest: a separate action that stays off until switched on
        accept.click()
        settle(pg, 3000)
        loan = pg.locator("input[type=checkbox][aria-label^='Finance']").first
        loan.check()
        settle(pg, 3000)
        if want("04-loan"):
            shot(pg, "04-loan", chart_top, bottom(pg.get_by_text("Includes the actions that are switched on."), 14))
        loan.uncheck()   # the volatile what-if would dominate every later chart
        pg.locator("input[type=checkbox][aria-label^='Invest CHF']").first.uncheck()
        settle(pg, 3000)

        # 5. options from another company
        pg.get_by_role("button", name="Ask for options").click()
        pg.get_by_text("options from Alpenschutz").wait_for(timeout=60000)
        settle(pg, 2000)
        if want("05-partners"):
            shot(pg, "05-partners", top(pg.get_by_text("Options from other companies"), 20), bottom(pg.get_by_text("What came back"), 24))
        pg.get_by_text("Options from other companies").first.scroll_into_view_if_needed()

        # 6. the advisor's view (pro mode, second tab)
        pg.get_by_role("button", name="Pro mode").click()
        pg.wait_for_selector(".recharts-surface")
        settle(pg, 4000)
        pg.get_by_role("button", name="Advisor").click()
        settle(pg, 4000)
        if want("06-advisor"):
            shot(pg, "06-advisor", top(pg.get_by_text("Simple view"), 12), top(pg.get_by_text("Ask the client"), 16), x=(88, 1352))
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--client", type=int, default=0, help="index in /api/clients; it is reset first")
    ap.add_argument("--only", default="", help="comma-separated shot numbers, e.g. 03,05")
    a = ap.parse_args()
    run(a.base, {s for s in a.only.split(",") if s}, a.client)
