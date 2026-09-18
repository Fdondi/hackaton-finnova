"""Baseline = the engine's starting point, derived from the profile. Pure numbers + assumptions."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from typing import TYPE_CHECKING

from ..config import Config
from ..model import Assumption, AssumptionBook, Client, add_months, month_start
from ..profile import Profile

if TYPE_CHECKING:
    from ..population import RiskProfile


class Baseline(BaseModel):
    client_id: str
    start: date                    # first simulated month
    birth_year: int | None
    age: float
    canton: str | None
    cash: float
    invested: float
    p3a: float
    p2: float
    salary_net_monthly: float      # average incl. 13th
    other_income_monthly: float
    gross_income_annual: float
    fixed_costs_monthly: float
    variable_costs_monthly: float
    contrib_p3a_monthly: float
    contrib_invested_monthly: float
    buffer_reserve: float          # today's CHF kept aside, never spent on goals
    p2_insured_salary: float
    p2_age_credits: dict[int, float] = Field(default_factory=dict)
    housing_monthly: float
    spending_by_category: dict[str, float] = Field(default_factory=dict)
    portfolio: str = "balanced"
    p3a_portfolio: str = "balanced"
    assumptions: list[Assumption] = Field(default_factory=list)

    @property
    def spending_monthly(self) -> float:
        return self.fixed_costs_monthly + self.variable_costs_monthly

    def age_at(self, d: date) -> float:
        if self.birth_year is None:
            return self.age + (d.year - self.start.year) + (d.month - self.start.month) / 12
        return d.year - self.birth_year + (d.month - 6) / 12


def build_baseline(profile: Profile, client: Client, cfg: Config, book: AssumptionBook,
                   risk: "RiskProfile | None" = None) -> Baseline:
    """With `risk`, the client's own big one-off bills leave the variable-spending average: the engine draws them as
    random shocks instead (same mean over time, but they arrive in lumps, which is what drains a reserve)."""
    profile_values = {a.key: book.add(a) for a in profile.assumptions}   # gross income, pillar 2: editable here too
    start = add_months(month_start(profile.as_of), 1)
    buffer_months = book.get("buffer_months", cfg.get_path("app.planning.buffer_months", 3),
                             label="Emergency reserve kept aside", unit="months of fixed costs", source="market_default",
                             low=0, high=12, step=1)
    net = book.get("salary_net_monthly", profile.income.salary_net_monthly_avg, label="Net salary per month (incl. 13th)",
                   source="transactions", unit="CHF/month", step=50)
    fixed = book.get("fixed_costs_monthly", profile.fixed_costs_monthly, label="Fixed costs per month",
                     source="transactions", unit="CHF/month", step=50)
    lumpy = risk.personal_bill_monthly if risk is not None else 0.0
    variable = book.get("variable_costs_monthly", profile.variable_costs_monthly - lumpy, label="Variable spending per month",
                        source="transactions", unit="CHF/month", step=50,
                        note=f"Without one-off bills over CHF {risk.bill_threshold:,.0f} (about CHF {lumpy:,.0f}/month): "
                             "they are simulated as random shocks".replace(",", "'") if lumpy > 0 else None)
    # facts the client can correct on the facts page: each edit moves the matching total
    profile_housing, profile_car = profile.monthly("housing"), profile.monthly("transport_car")
    housing = book.get("housing_monthly", profile_housing, label="Housing costs per month (rent or mortgage)",
                       source="transactions", unit="CHF/month", step=50)
    car = book.get("car_monthly", profile_car, label="Car costs per month", source="transactions", unit="CHF/month", step=10)
    fixed += housing - profile_housing
    variable += car - profile_car
    other_income = book.get("other_income_monthly", profile.income.other_income_monthly, label="Other income per month",
                            source="transactions", unit="CHF/month", step=50)
    contrib_p3a = book.get("contrib_p3a_monthly", profile.saving_contrib_monthly.get("p3a", 0.0),
                           label="Pillar 3a payments per month", source="transactions", unit="CHF/month", step=50)
    cash = book.get("cash", profile.balances.liquid, label="Cash on your accounts", source="transactions", step=1000)
    invested = book.get("invested", profile.balances.invested, label="Investments", source="client_data", step=1000)
    p3a = book.get("p3a_balance", profile.balances.p3a, label="Pillar 3a savings", source="client_data", step=1000)
    bvg = cfg["pension"]["bvg"]
    gross = profile_values.get("gross_income_annual", profile.income.gross_annual)
    p2 = profile_values.get("pillar2_balance", profile.balances.p2)
    insured = client.pension.pillar2_insured_salary or max(0.0, min(gross, bvg["max_insured_salary"]) - bvg["coordination_deduction"])
    return Baseline(
        client_id=client.id, start=start, birth_year=client.birth_year, age=float(profile.age or 40), canton=client.canton,
        cash=cash, invested=invested, p3a=p3a, p2=p2,
        salary_net_monthly=net, other_income_monthly=other_income, gross_income_annual=gross,
        fixed_costs_monthly=fixed, variable_costs_monthly=variable,
        contrib_p3a_monthly=contrib_p3a,
        contrib_invested_monthly=profile.saving_contrib_monthly.get("invested", 0.0),
        buffer_reserve=buffer_months * fixed, p2_insured_salary=insured,
        p2_age_credits={int(k): float(v) for k, v in bvg["age_credits"].items()},
        housing_monthly=housing,
        spending_by_category={f.category: f.monthly for f in profile.flows if f.kind == "spending"},
        portfolio=cfg.get_path("market.default_portfolio", "balanced"),
        p3a_portfolio=cfg.get_path("market.p3a_default_portfolio", "balanced"),
        assumptions=book.list(),
    )
