"""Market & risk parameters, converted to monthly terms. Editable via the assumption book."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..config import Config
from ..model import AssumptionBook

if TYPE_CHECKING:
    from ..population import RiskProfile


@dataclass
class Market:
    inflation_mean: float
    inflation_sd: float
    cash_rate: float
    overdraft_rate: float
    real_wage_growth: float
    portfolios: dict[str, tuple[float, float]]   # name -> (expected return, volatility)
    house_growth_mean: float
    house_growth_sd: float
    job_loss_prob: float
    job_loss_median_months: float
    job_loss_sigma: float
    replacement_rate: float
    expense_noise_sd: float
    haircut_floor: float
    haircut_tau: float
    p2_rate: float
    bill_rate: float = 0.0            # one-off bills per year (compound Poisson), today's CHF lognormal sizes
    bill_mu: float = 0.0
    bill_sigma: float = 0.0

    def monthly_lognormal(self, portfolio: str, expected_return: float | None = None) -> tuple[float, float]:
        r, vol = self.portfolios.get(portfolio, self.portfolios["balanced"])
        r = r if expected_return is None else expected_return
        sd = vol / math.sqrt(12)
        return math.log(1 + r) / 12 - 0.5 * sd * sd, sd


def build_market(cfg: Config, book: AssumptionBook, risk: "RiskProfile | None" = None) -> Market:
    """`risk` (population data) replaces the generic job-loss / spending-noise defaults and switches on one-off bills."""
    m = cfg["market"]
    bills = m.get("big_bills", {})
    job_prob, job_months, noise = m["job_loss"]["annual_prob"], m["job_loss"]["duration_median_months"], m["expense_noise_sd"]
    job_src, job_label, job_note = "market_default", "Chance of losing your job in a year", None
    bill_rate, bill_mu, bill_sigma = bills.get("annual_rate", 0.0), bills.get("size_mu", 0.0), bills.get("size_sigma", 0.0)
    if risk is not None:
        if risk.salary_gap_prob is not None:
            job_prob, job_src = risk.salary_gap_prob, "population"
            job_months = risk.salary_gap_months or job_months
            job_label = "Chance of a gap in salary in a year"
            job_note = f"Measured on {risk.segment_label} in the bank's data; typical gap {job_months:.0f} month(s)"
        noise = risk.expense_noise_sd or noise
        bill_mu, bill_sigma = risk.bill_mu, risk.bill_sigma
        bill_rate = book.get("big_bill_rate", risk.bill_rate, label=f"Unexpected bills over CHF {risk.bill_threshold:,.0f} per year".replace(",", "'"),
                             unit="per year", source="population", low=0.0, high=6.0, step=0.1,
                             note=f"{risk.segment_label}: {risk.segment_rate:.1f} a year, typically CHF {risk.bill_p50 or 0:,.0f}; "
                                  f"you had {risk.personal_bills} in the last 12 months".replace(",", "'"))
    port = dict(m["portfolios"])
    default = m.get("default_portfolio", "balanced")
    ret = book.get("portfolio_return", port[default]["expected_return"], label=f"Expected return, {default} portfolio",
                   unit="%/yr", source="market_default", low=0.0, high=0.08, step=0.005)
    vol = book.get("portfolio_volatility", port[default]["volatility"], label=f"Volatility, {default} portfolio",
                   unit="%/yr", source="market_default", low=0.0, high=0.25, step=0.01)
    portfolios = {k: (v["expected_return"], v["volatility"]) for k, v in port.items()}
    portfolios[default] = (ret, vol)
    return Market(
        inflation_mean=book.get("inflation", m["inflation"]["mean"], label="Inflation", unit="%/yr", source="market_default",
                                low=0.0, high=0.03, step=0.0025),
        inflation_sd=m["inflation"]["sd"],
        cash_rate=book.get("cash_rate", m["cash_rate"], label="Interest on savings accounts", unit="%/yr",
                           source="market_default", low=0.0, high=0.02, step=0.0025),
        overdraft_rate=m["overdraft_rate"],
        real_wage_growth=book.get("real_wage_growth", m["real_wage_growth"], label="Real salary growth", unit="%/yr",
                                  source="market_default", low=-0.01, high=0.02, step=0.0025),
        portfolios=portfolios,
        house_growth_mean=book.get("house_price_growth", m["house_price_growth"]["mean"], label="Home price growth",
                                   unit="%/yr", source="market_default", low=-0.02, high=0.05, step=0.005),
        house_growth_sd=m["house_price_growth"]["sd"],
        job_loss_prob=book.get("job_loss_prob", job_prob, label=job_label, unit="%/yr", source=job_src, low=0.0,
                               high=max(0.1, job_prob), step=0.005, note=job_note),
        job_loss_median_months=job_months,
        job_loss_sigma=m["job_loss"]["duration_sigma"],
        replacement_rate=m["job_loss"]["replacement_rate"],
        expense_noise_sd=noise,
        haircut_floor=book.get("behavioural_floor", m["behavioural_haircut"]["floor"],
                               label="Share of a behavioural saving that sticks long-term", unit="share",
                               source="market_default", low=0.2, high=1.0, step=0.05),
        haircut_tau=m["behavioural_haircut"]["tau_months"],
        p2_rate=cfg.get_path("pension.bvg.min_interest", 0.0125),
        bill_rate=bill_rate, bill_mu=bill_mu, bill_sigma=bill_sigma,
    )
