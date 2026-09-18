from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..model import Assumption


class RecurringGroup(BaseModel):
    key: str
    merchant: str
    category: str
    period_days: int
    period_label: str                  # weekly | monthly | quarterly | semiannual | yearly
    amount: float                      # signed, median of the last 3 payments
    monthly_equivalent: float          # signed
    count: int
    first_date: date
    last_date: date
    next_expected: date
    active: bool
    tags: list[str] = Field(default_factory=list)
    counterparty: str | None = None
    booking_ids: list[str] = Field(default_factory=list)


class MerchantTotal(BaseModel):
    merchant: str
    monthly: float
    count: int


class CategoryFlow(BaseModel):
    category: str
    kind: str
    label: str
    monthly: float                     # positive = spending/saving amount (for income: positive = inflow)
    fixed_monthly: float
    variable_monthly: float
    n_bookings: int
    opaque: bool = False
    discretionary: bool = False
    top_merchants: list[MerchantTotal] = Field(default_factory=list)


class IncomeProfile(BaseModel):
    salary_net_monthly_avg: float      # annual net salary / 12 (includes the 13th)
    salary_payment: float              # typical monthly payment
    has_13th: bool
    employer: str | None = None
    other_income_monthly: float = 0.0
    volatility_cv: float = 0.0
    gross_annual: float
    gross_source: Literal["client_data", "market_default", "user"] = "market_default"


class Balances(BaseModel):
    liquid: float
    invested: float
    p3a: float
    p2: float
    p2_source: Literal["client_data", "market_default", "user"] = "client_data"
    by_account: dict[str, float] = Field(default_factory=dict)


class Trend(BaseModel):
    liquid_12m_ago: float
    liquid_now: float
    change: float
    direction: Literal["up", "flat", "down"]


class AssetHint(BaseModel):
    kind: str                          # car | property | boat | hobby | side_business | ...
    label: str
    monthly_cost: float = 0.0          # positive CHF/month
    evidence: list[str] = Field(default_factory=list)          # merchant names, for display
    booking_ids: list[str] = Field(default_factory=list)       # exact raw bookings behind this hint
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.7


class DataNote(BaseModel):
    level: Literal["info", "warning"]
    message: str


class Profile(BaseModel):
    client_id: str
    as_of: date
    age: int | None
    window_start: date
    window_months: int
    covered_months: int
    missing_months: list[str]
    history_months: int
    income: IncomeProfile
    flows: list[CategoryFlow]
    spending_monthly: float
    fixed_costs_monthly: float
    variable_costs_monthly: float
    saving_contrib_monthly: dict[str, float]
    free_cash_flow_monthly: float      # income - spending (before own savings contributions)
    savings_rate: float
    balances: Balances
    buffer_months: float
    trend: Trend
    opaque_monthly: float
    opaque_share: float
    opaque_breakdown: dict[str, float]
    recurring: list[RecurringGroup]
    hints: list[AssetHint]
    data_quality: list[DataNote]
    assumptions: list[Assumption] = Field(default_factory=list)

    def flow(self, category: str) -> CategoryFlow | None:
        return next((f for f in self.flows if f.category == category), None)

    def monthly(self, category: str) -> float:
        f = self.flow(category)
        return f.monthly if f else 0.0

    def hint(self, kind: str) -> AssetHint | None:
        return next((h for h in self.hints if h.kind == kind), None)
