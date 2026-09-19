"""Demo health insurers with an assistant-accessible API, answering in the scenario format.

    mock_insurer     the client's current insurer (Alpenschutz): knows today's premium, offers other deductibles/models
    mock_competitor  another insurer (Rigi): quotes its own prices; doesn't know what the client pays today, so it
                     uses replace_spending and the bank fills in today's premium from the account

Prices come from the insurer_quotes service (mock premium table), expected out-of-pocket costs from the KVG cost model.
Demo shortcut: each insurer's customer file (age, canton, household, deductible, model) is simulated from the bank's
client record, found via customer_ref (a real one would know the customer from the account link).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from ..specialists.kvg import oop
from .connectors import connector
from .contract import FORMAT

if TYPE_CHECKING:
    from ..service import PlanningService

MODELS = {"en": {"standard": "standard model", "family_doctor": "family doctor model", "hmo": "HMO model", "telmed": "telmed model"},
          "de": {"standard": "Standardmodell", "family_doctor": "Hausarztmodell", "hmo": "HMO-Modell", "telmed": "Telmed-Modell"}}
TEXT = {
    "en": {"title": "Deductible CHF {d} ({model})", "switch_title": "Switch to {name}: deductible CHF {d} ({model})",
           "description": "Premium CHF {new}/month instead of CHF {now}; {oop}.",
           "switch_description": "Premium CHF {new}/month; {oop}.",
           "oop_more": "you expect to pay about CHF {x} a year more yourself", "oop_less": "you expect to pay about CHF {x} a year less yourself",
           "oop_same": "your own share of costs stays the same",
           "bad_year": "In a bad health year you pay up to CHF {x} more yourself",
           "hmo": "You always go to one of our HMO group practices first", "telmed": "You always call our telemedicine line first",
           "family_doctor": "You always see your family doctor first", "standard": "Free choice of doctor",
           "deadline": "Tell us by 30 November; the change starts on 1 January",
           "switch_deadline": "Cancel your current basic insurance by 30 November; we take over on 1 January",
           "premium_now": "Premium today", "premium_new": "New premium", "oop_label": "Expected change in own costs",
           "note": "Prices for next year from our tariff; out-of-pocket costs are expectations for your age group, not a promise."},
    "de": {"title": "Franchise CHF {d} ({model})", "switch_title": "Wechsel zu {name}: Franchise CHF {d} ({model})",
           "description": "Prämie CHF {new}/Monat statt CHF {now}; {oop}.",
           "switch_description": "Prämie CHF {new}/Monat; {oop}.",
           "oop_more": "Sie zahlen voraussichtlich rund CHF {x} im Jahr mehr selbst", "oop_less": "Sie zahlen voraussichtlich rund CHF {x} im Jahr weniger selbst",
           "oop_same": "Ihr Selbstbehalt bleibt gleich",
           "bad_year": "In einem schlechten Gesundheitsjahr zahlen Sie bis zu CHF {x} mehr selbst",
           "hmo": "Sie gehen immer zuerst in eine unserer HMO-Gruppenpraxen", "telmed": "Sie rufen immer zuerst unsere Telemedizin-Hotline an",
           "family_doctor": "Sie gehen immer zuerst zu Ihrer Hausärztin oder Ihrem Hausarzt", "standard": "Freie Arztwahl",
           "deadline": "Bis 30. November melden; die Änderung gilt ab 1. Januar",
           "switch_deadline": "Die bisherige Grundversicherung bis 30. November kündigen; wir übernehmen ab 1. Januar",
           "premium_now": "Prämie heute", "premium_new": "Neue Prämie", "oop_label": "Erwartete Änderung der eigenen Kosten",
           "note": "Preise fürs nächste Jahr aus unserem Tarif; die eigenen Kosten sind Erwartungswerte Ihrer Altersgruppe, kein Versprechen."},
}


def chf(x: float) -> str:
    return f"{round(x):,}".replace(",", "'")


def _plans(req: dict[str, Any], partner: dict[str, Any], svc: "PlanningService", competitor: bool) -> dict[str, Any]:
    lang = req.get("language") if req.get("language") in TEXT else "en"
    tx, names = TEXT[lang], MODELS[lang]
    st = svc.state(str(req["customer_ref"]))
    client, profile, cfg = st.ds.client, st.profile, svc.cfg
    k = cfg["kvg"]
    rate, cap = k["copay_rate"], k["copay_cap_adult"]
    quotes = svc.services["insurer_quotes"]
    age, adults = profile.age or 40, max(1, client.household.adults)
    d0 = int(client.health.deductible or 300)
    m0 = client.health.model or "standard"
    factor = float(partner.get("price_factor", 1.0))

    def q(d: int, m: str) -> float:
        return quotes.quote(age=age, canton=client.canton, deductible=d, model=m)

    alt = "telmed" if m0 != "telmed" else "hmo"
    if competitor:           # its own tariff for the whole household; what the client pays today is the bank's to know
        options = [(d0, m0), (d0, alt)] + ([(2500, m0)] if d0 != 2500 else [])
        now = None
    else:                    # the current insurer knows today's premium
        options = [(d, m0) for d in (300, 1500, 2500) if d != d0] + [(d0, alt)] + ([(2500, alt)] if d0 != 2500 else [])
        now = client.health.premium_monthly or profile.monthly("health_premium") or adults * q(d0, m0)
    prior = cfg.by_age("kvg.cost_model.age_bands", int(age))
    rng = np.random.default_rng(11)
    costs = np.where(rng.uniform(size=(adults, 4000)) < prior["p_zero"], 0.0,
                     prior["median_positive"] * np.exp(prior["sigma"] * rng.standard_normal((adults, 4000))))
    m = profile.as_of.month
    start = 13 - m if m > 1 else 12                     # months to 1 January

    scenarios = []
    for d, model in options[:5]:
        if now is None:
            new = factor * adults * q(d, model)
            premium = {"primitive": "replace_spending", "category": "health_premium",
                       "new_monthly": {"value": round(new, 2), "label": tx["premium_new"], "unit": "CHF/month"}, "start_in_months": start}
        else:   # discounts are per adult; children's premiums stay as they are
            new = now + adults * (q(d, model) - q(d0, m0))
            premium = {"primitive": "substitute", "remove_monthly": {"value": round(now, 2), "label": tx["premium_now"], "unit": "CHF/month"},
                       "add_monthly": {"value": round(new, 2), "label": tx["premium_new"], "unit": "CHF/month"}, "start_in_months": start}
        extra = (oop(d, costs, rate, cap) - oop(d0, costs, rate, cap)).sum(axis=0)   # CHF/year, per simulated year
        mean, p10, p90 = float(extra.mean()), float(np.percentile(extra, 10)), float(np.percentile(extra, 90))
        parts = [premium]
        if abs(mean) > 10:
            lo, hi = sorted((-p90 / 12, -p10 / 12))
            parts.append({"primitive": "recurring_change", "start_in_months": start,
                          "monthly_delta": {"value": round(-mean / 12, 2), "low": round(lo, 2), "high": round(hi, 2),
                                            "label": tx["oop_label"], "unit": "CHF/month"}})
        oop_text = (tx["oop_more"] if mean > 10 else tx["oop_less"] if mean < -10 else tx["oop_same"]).format(x=chf(abs(mean)))
        side = [tx[model], tx["switch_deadline" if competitor else "deadline"]]
        if d > d0:
            side.insert(0, tx["bad_year"].format(x=chf(adults * (d - d0))))
        short = partner.get("name", "us").split(" (")[0]
        scenarios.append({
            "title": (tx["switch_title"] if competitor else tx["title"]).format(name=short, d=chf(d), model=names.get(model, model)),
            "description": (tx["switch_description"] if competitor else tx["description"]).format(new=chf(new), now=chf(now or 0), oop=oop_text),
            "effort": "medium" if competitor else "low", "side_effects": side, "parts": parts})
    return {"format": FORMAT, "source": partner.get("name", "Demo insurer"), "pick_one": True, "note": tx["note"], "scenarios": scenarios}


@connector("mock_insurer")
def mock_insurer(req: dict[str, Any], partner: dict[str, Any], svc: "PlanningService") -> dict[str, Any]:
    return _plans(req, partner, svc, competitor=False)


@connector("mock_competitor")
def mock_competitor(req: dict[str, Any], partner: dict[str, Any], svc: "PlanningService") -> dict[str, Any]:
    return _plans(req, partner, svc, competitor=True)
