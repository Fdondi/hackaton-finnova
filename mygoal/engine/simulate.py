"""Monthly Monte Carlo over a household balance sheet.

State per path: cash (liquid), invested, pillar 3a, pillar 2. Stochastic: inflation, asset returns,
home prices, job loss (with unemployment benefits), variable spending noise, one-off bills (when the population
data calibrates them), plus whatever distributions the levers carry. Vectorised over paths, looped over months: readable and ~20-60 ms.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np

from ..model import LeverImpact, add_months, months_between
from .baseline import Baseline
from .compile import compile_impacts
from .market import Market
from .random import bank_for

BUCKETS = ("cash", "invested", "p3a", "p2")


@dataclass
class Trajectories:
    start: date
    T: int
    N: int
    cash: np.ndarray          # (T+1, N); index i = state at the start of month add_months(start, i)
    invested: np.ndarray
    p3a: np.ndarray
    p2: np.ndarray
    price: np.ndarray         # consumer price index (1 = today)
    house: np.ndarray         # home price index
    gross: np.ndarray         # annualised gross income (0 while unemployed)
    market: np.ndarray        # cumulative "growth" portfolio return index (1 = today), independent of cash flows
    breach: np.ndarray        # (N,) liquid assets fell below one month of spending at some point
    settings: dict

    def date_at(self, i: int) -> date:
        return add_months(self.start, int(i))

    def idx(self, d: date) -> int:
        return months_between(self.start, d)


def _credit_rates(base: Baseline, T: int) -> np.ndarray:
    credits = sorted(base.p2_age_credits.items())
    out = np.zeros(T)
    for t in range(T):
        age = base.age_at(add_months(base.start, t))
        rate = [v for a, v in credits if age >= a]
        out[t] = rate[-1] if rate and age < 65 else 0.0
    return out


def simulate(base: Baseline, impacts: list[LeverImpact], market: Market, T: int, N: int, seed: int) -> Trajectories:
    rb = bank_for(seed, T, N)
    comp = compile_impacts(impacts, base.start, T, N, seed, market)
    mu_i, sd_i = market.monthly_lognormal(str(comp.settings.get("portfolio", base.portfolio)), comp.settings.get("portfolio_return"),
                                          comp.settings.get("portfolio_volatility"))
    mu_3, sd_3 = market.monthly_lognormal(str(comp.settings.get("p3a_portfolio", base.p3a_portfolio)))
    infl_mu, infl_sd = market.inflation_mean / 12, market.inflation_sd / math.sqrt(12)
    h_mu, h_sd = market.house_growth_mean / 12, market.house_growth_sd / math.sqrt(12)
    p_job = 1 - (1 - market.job_loss_prob) ** (1 / 12)
    noise_sd = market.expense_noise_sd
    credit = _credit_rates(base, T)
    transfers_at: dict[int, list] = {}
    for tr in comp.transfers:
        transfers_at.setdefault(tr[0], []).append(tr)
    withdrawals_at: dict[int, list] = {}
    for w in comp.withdrawals:
        withdrawals_at.setdefault(w[0], []).append(w)
    to_p3a = comp.to_bucket_monthly.get("p3a")
    to_inv = comp.to_bucket_monthly.get("invested")
    to_p2 = comp.to_bucket_monthly.get("p2")

    # ---- everything that doesn't depend on balances is computed for all months at once ----
    price = np.cumprod(1 + infl_mu + infl_sd * rb.z_infl, axis=0)
    wage = np.cumprod(1 + infl_mu + infl_sd * rb.z_infl + market.real_wage_growth / 12, axis=0)
    house = np.cumprod(1 + h_mu + h_sd * rb.z_house, axis=0)
    employed = np.empty((T, N), dtype=bool)
    unemployed_left = np.zeros(N)
    durations = np.ceil(market.job_loss_median_months * np.exp(market.job_loss_sigma * rb.z_job_duration))
    for t in range(T):
        lose = (unemployed_left <= 0) & (rb.u_job[t] < p_job)
        unemployed_left = np.where(lose, durations[t], unemployed_left)
        employed[t] = unemployed_left <= 0
        unemployed_left = np.maximum(unemployed_left - 1, 0)

    income = base.salary_net_monthly * wage * comp.salary_factor * np.where(employed, 1.0, market.replacement_rate) \
        + base.other_income_monthly * price
    # fixed costs follow prices; variable spending follows wages (people spend more as they earn more)
    spending = base.fixed_costs_monthly * price \
        + base.variable_costs_monthly * np.exp(noise_sd * rb.z_expense - 0.5 * noise_sd**2) * wage
    if market.bill_rate > 0:   # at most one bill a month, with the right mean: P = rate / 12
        hit = rb.u_bill < min(market.bill_rate / 12, 1.0)
        spending = spending + hit * np.exp(market.bill_mu + market.bill_sigma * rb.z_bill) * price
    c3 = (base.contrib_p3a_monthly + (to_p3a if to_p3a is not None else 0.0)) * price
    ci = (base.contrib_invested_monthly + (to_inv if to_inv is not None else 0.0)) * price
    c2 = (to_p2 * price) if to_p2 is not None else np.zeros((T, N))
    net_cash = income - spending + comp.flow * price + comp.flow_nominal - c3 - ci - c2
    gross = base.gross_income_annual * wage * comp.gross_factor * employed
    p2_credit = credit[:, None] * base.p2_insured_salary * wage * comp.gross_factor * employed / 12
    ret_inv = np.exp(mu_i + sd_i * rb.z_market)
    ret_3a = np.exp(mu_3 + sd_3 * rb.z_market)
    market_index = np.cumprod(ret_inv, axis=0)
    one_off = {b: arr * price for b, arr in comp.one_off.items()}
    cash_up, cash_down, p2_up = 1 + market.cash_rate / 12, 1 + market.overdraft_rate / 12, 1 + market.p2_rate / 12

    # ---- balance-dependent part, month by month ----
    state = {"cash": np.full(N, base.cash), "invested": np.full(N, base.invested),
             "p3a": np.full(N, base.p3a), "p2": np.full(N, base.p2)}
    breach = np.zeros(N, dtype=bool)
    pots = [np.zeros(N) for _ in comp.pots]         # committed investments, each with its own return and risk
    rec = {k: np.empty((T + 1, N), dtype=np.float32) for k in BUCKETS}
    for k in BUCKETS:
        rec[k][0] = state[k]

    for t in range(T):
        state["cash"] += net_cash[t]
        state["p3a"] += c3[t]
        state["invested"] += ci[t]
        state["p2"] += c2[t]
        for b, arr in one_off.items():
            state[b] += arr[t]
        for _, src, dst, amount in transfers_at.get(t, []):
            move = np.minimum(amount * price[t], np.maximum(state[src], 0.0))
            state[src] -= move
            state[dst] += move
        for pot, (t0, once, monthly, _, _, src) in zip(pots, comp.pots):
            if t < t0:
                continue
            add = np.zeros(N)
            if t == t0 and once is not None:
                add += np.minimum(once * price[t], np.maximum(state[src], 0.0))
            if monthly is not None:
                add += monthly * price[t]
            state[src] -= add
            pot += add
        for _, amount, order, caps, house_indexed in withdrawals_at.get(t, []):
            index = house[t] if house_indexed else price[t]
            need = amount * index
            for b in order:
                own = np.maximum(state[b], 0.0)
                pooled = sum(pots) if (b == "invested" and pots) else 0.0     # committed investments can be sold too
                avail = own + pooled
                if caps.get(b) is not None:
                    avail = np.minimum(avail, caps[b] * index)
                take = np.minimum(need, avail)
                from_own = np.minimum(take, own)
                state[b] -= from_own
                if pots and b == "invested":
                    rest = take - from_own
                    total = np.maximum(pooled, 1e-9)
                    for pot in pots:
                        pot -= rest * pot / total
                need = need - take
            state["cash"] -= need

        cash = state["cash"]
        state["cash"] = cash * np.where(cash > 0, cash_up, cash_down)
        state["invested"] *= ret_inv[t]
        state["p3a"] *= ret_3a[t]
        state["p2"] = state["p2"] * p2_up + p2_credit[t]
        for pot, (_, _, _, mu, sd, _) in zip(pots, comp.pots):
            pot *= np.exp(mu + sd * rb.z_market[t])
        sell = np.minimum(np.maximum(-state["cash"], 0.0), np.maximum(state["invested"], 0.0))
        state["invested"] -= sell
        state["cash"] += sell
        pooled = sum(pots) if pots else 0.0
        breach |= (state["cash"] + state["invested"] + pooled) < spending[t]
        for k in BUCKETS:
            rec[k][t + 1] = state[k] + (pooled if k == "invested" else 0.0)

    one = np.ones((1, N))
    return Trajectories(start=base.start, T=T, N=N, cash=rec["cash"], invested=rec["invested"], p3a=rec["p3a"],
                        p2=rec["p2"], price=np.vstack([one, price]).astype(np.float32),
                        house=np.vstack([one, house]).astype(np.float32),
                        gross=np.vstack([np.full((1, N), base.gross_income_annual), gross]).astype(np.float32),
                        market=np.vstack([one, market_index]).astype(np.float32),
                        breach=breach, settings=comp.settings)
