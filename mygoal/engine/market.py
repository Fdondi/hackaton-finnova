"""Market & risk parameters, converted to monthly terms. Editable via the assumption book."""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import Config
from ..model import AssumptionBook


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

    def monthly_lognormal(self, portfolio: str) -> tuple[float, float]:
        r, vol = self.portfolios.get(portfolio, self.portfolios["balanced"])
        sd = vol / math.sqrt(12)
        return math.log(1 + r) / 12 - 0.5 * sd * sd, sd


def build_market(cfg: Config, book: AssumptionBook) -> Market:
    m = cfg["market"]
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
        job_loss_prob=book.get("job_loss_prob", m["job_loss"]["annual_prob"], label="Chance of losing your job in a year",
                               unit="%/yr", source="market_default", low=0.0, high=0.1, step=0.005),
        job_loss_median_months=m["job_loss"]["duration_median_months"],
        job_loss_sigma=m["job_loss"]["duration_sigma"],
        replacement_rate=m["job_loss"]["replacement_rate"],
        expense_noise_sd=m["expense_noise_sd"],
        haircut_floor=book.get("behavioural_floor", m["behavioural_haircut"]["floor"],
                               label="Share of a behavioural saving that sticks long-term", unit="share",
                               source="market_default", low=0.2, high=1.0, step=0.05),
        haircut_tau=m["behavioural_haircut"]["tau_months"],
        p2_rate=cfg.get_path("pension.bvg.min_interest", 0.0125),
    )
