"""Canonical data model. Adapters produce these; nothing downstream reads raw data.

Money is float (CHF) on purpose: this is a projection tool, and numpy needs floats.
Unknown raw fields go into `extra` so nothing is lost when the real data has more columns.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .goals import GoalSpec

CategorySource = Literal["internal", "bank", "rule", "merchant", "mcc", "llm", "user", "fallback"]
AccountType = Literal["private", "savings", "3a", "securities", "mortgage", "card", "other"]


class Booking(BaseModel):
    id: str
    account_id: str
    booking_date: date
    value_date: date | None = None
    amount: float                       # signed, + = money in
    currency: str = "CHF"
    text: str = ""                      # booking text + remittance info
    counterparty: str | None = None
    counterparty_iban: str | None = None
    mcc: str | None = None
    bank_tx_code: str | None = None     # ISO 20022 BkTxCd, e.g. PMNT-RCDT-SALA
    bank_category: str | None = None    # if the bank already categorises, we trust it first
    extra: dict[str, Any] = Field(default_factory=dict)
    # derived by the categoriser / profile builder
    category: str | None = None
    category_source: CategorySource | None = None
    merchant: str | None = None
    tags: list[str] = Field(default_factory=list)
    recurring_group: str | None = None


class Account(BaseModel):
    id: str
    client_id: str
    type: AccountType = "private"
    balance: float = 0.0
    currency: str = "CHF"
    name: str | None = None
    iban: str | None = None


class Position(BaseModel):
    account_id: str
    name: str
    value: float
    asset_class: str = "equity"


class Household(BaseModel):
    adults: int = 1
    partner_birth_year: int | None = None
    children_birth_years: list[int] = Field(default_factory=list)


class PensionInfo(BaseModel):
    pillar2_balance: float | None = None
    pillar2_insured_salary: float | None = None
    pillar3a_balance: float | None = None   # when 3a is not delivered as an account


class HealthInfo(BaseModel):
    deductible: int | None = None
    premium_monthly: float | None = None
    insurer: str | None = None
    model: str | None = None                # standard | family_doctor | hmo | telmed
    premium_region: str | None = None


class Client(BaseModel):
    id: str
    name: str | None = None
    birth_year: int | None = None
    canton: str | None = None
    gross_income_annual: float | None = None
    household: Household = Field(default_factory=Household)
    pension: PensionInfo = Field(default_factory=PensionInfo)
    health: HealthInfo = Field(default_factory=HealthInfo)
    goals: list[GoalSpec] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)


class Dataset(BaseModel):
    """Everything an adapter knows about one client."""
    client: Client
    accounts: list[Account]
    bookings: list[Booking]
    positions: list[Position] = Field(default_factory=list)
    as_of: date
    source: str = "unknown"
