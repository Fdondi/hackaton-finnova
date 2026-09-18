"""Car specialist: detect the car from bookings, then price "live without it" against the cheapest
mix of GA / Halbtax + tickets / car sharing for the kilometres the client still needs."""
from __future__ import annotations

from ..config import load_config
from ..levers import LeverContext, lever
from ..model import LeverImpact, OneOff, RecurringDelta, add_months, fixed, triangular
from ..profile import AssetHint, HintContext, hint_detector
from ..swiss import fmt_chf

CAR_CATEGORIES = ("transport_car", "car_financing")


@hint_detector("car")
def detect_car(ctx: HintContext) -> list[AssetHint]:
    monthly = sum(ctx.flows[c].monthly for c in CAR_CATEGORIES if c in ctx.flows)
    if monthly < 80:
        return []
    cfg = load_config()["prices"]["car"]
    rows = ctx.window[ctx.window["category"].isin(CAR_CATEGORIES)]

    def by_tag(tag: str) -> float:
        return round(-float(rows[rows["tags"].map(lambda t: tag in t)]["amount"].sum()) / ctx.covered_months, 2)

    parts = {t: by_tag(t) for t in ("leasing", "fuel", "car_insurance", "vehicle_tax", "parking", "service")}
    insured = [r for r in ctx.recurring if r.active and "car_insurance" in r.tags]
    taxed = [r for r in ctx.recurring if r.active and "vehicle_tax" in r.tags]
    n_cars = max(1, len(insured), len(taxed))
    km = parts["fuel"] * 12 / cfg["fuel_price_per_litre"] / (cfg["consumption_l_per_100km"] / 100)
    merchants = rows.groupby("merchant")["amount"].sum().sort_values().index[:6].tolist()
    return [AssetHint(kind="car", label="Car (leased)" if parts["leasing"] > 0 else "Car", monthly_cost=round(monthly, 2),
                      evidence=merchants, booking_ids=list(rows["id"]),
                      details={**parts, "km_per_year": round(km, -2), "leased": parts["leasing"] > 0, "n_cars": n_cars},
                      confidence=0.9)]


def transit_basket(km_transit: float, km_car: float, prices: dict, current_pt_monthly: float) -> dict[str, float]:
    """Yearly cost of each replacement option (CHF). Car sharing covers the km that still need a car."""
    pt, cs = prices["public_transport"], prices["car_sharing"]
    sharing = km_car * cs["km_rate"] + km_car / cs["km_per_hour_of_booking"] * cs["hourly_rate"] + cs["subscription_annual"]
    return {
        "GA travelcard": pt["ga_2nd_class_annual"] + sharing - current_pt_monthly * 12,
        "Half-fare card + tickets": pt["halbtax_annual"] + km_transit * pt["full_fare_chf_per_km"] * pt["half_fare_factor"] + sharing,
        "Tickets at full fare": km_transit * pt["full_fare_chf_per_km"] + sharing,
    }


@lever("give_up_car", origin="specialist")
def give_up_car(ctx: LeverContext):
    hint = ctx.profile.hint("car")
    if not hint:
        return None
    prices = ctx.cfg["prices"]
    d = hint.details
    a = ctx.book("give_up_car")
    second = d.get("n_cars", 1) >= 2       # households with two cars: price giving up the smaller one
    share_costs = 0.4 if second else 1.0
    running = a.get("car_costs_monthly", hint.monthly_cost * share_costs,
                    label="What the second car costs per month" if second else "What the car costs you per month",
                    unit="CHF/month", source="transactions", step=25, needs_confirmation=second,
                    note="Estimated as 40% of both cars' costs" if second else None)
    km = a.get("km_per_year", max(d["km_per_year"] * share_costs, 3000), label="Kilometres driven per year (from fuel spending)",
               unit="km/yr", source="transactions", low=round(d["km_per_year"] * share_costs * 0.6, -2),
               high=round(d["km_per_year"] * share_costs * 1.5, -2), step=500, needs_confirmation=True)
    share_car = a.get("share_still_car", 0.1 if second else 0.2, label="Share of those km that would still need a car", unit="share",
                      source="market_default", low=0.0, high=0.6, step=0.05, needs_confirmation=True,
                      note="With a second car at home, most trips can use the first one" if second else None)
    if d.get("leased"):
        months = int(a.get("months_to_lease_end", 6, label="Months until the lease ends", unit="months", source="market_default",
                           low=0, high=48, step=1, needs_confirmation=True))
        sale = 0.0
    else:
        months = int(a.get("months_to_sell", 2, label="Months to sell the car", unit="months", source="market_default", low=0, high=12, step=1))
        sale = a.get("sale_value", 9000 if second else 15000, label="What the car would sell for", source="market_default",
                     low=2000, high=40000, step=500, needs_confirmation=True)
    options = transit_basket(km * (1 - share_car), km * share_car, prices, ctx.profile.monthly("transport_public"))
    option, yearly = min(options.items(), key=lambda kv: kv[1])
    basket = max(yearly, 0.0) / 12
    start = add_months(ctx.start, months)
    net = running - basket
    title = "Sell the second car" if second else "Return the car when the lease ends" if d.get("leased") else "Sell the car"
    return LeverImpact(
        lever_id="give_up_car", title=title,
        description=f"Car costs {fmt_chf(running)}/month. The cheapest replacement ({option}, plus car sharing for "
                    f"{share_car:.0%} of the km) costs about {fmt_chf(basket)}/month.",
        group="structural", effort="high", confidence="estimated", icon="car",
        one_offs=[OneOff(at=start, amount=triangular(sale * 0.8, sale, sale * 1.05), label="Sale")] if sale > 0 else [],
        recurring=[RecurringDelta(start=start, monthly=fixed(running), label="Car costs stop", category="transport_car"),
                   RecurringDelta(start=start, monthly=fixed(-basket), label=option, category="transport_public")],
        side_effects=[f"Replacement: {option} + car sharing", "Some trips take longer, especially evenings and outside cities"],
        headline_monthly=round(net),
        details={"title_key": "give_up_second_car" if second else "give_up_leased_car" if d.get("leased") else "give_up_car",
                 "options_yearly": {k: round(v) for k, v in options.items()}, "chosen": option, "breakdown_monthly": {
            k: v for k, v in d.items() if isinstance(v, (int, float)) and k not in ("km_per_year",)}},
        assumptions=a.list(),
    )
