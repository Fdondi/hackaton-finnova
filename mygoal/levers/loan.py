"""Unsecured consumer loans: a separate action the client must switch on.

Homes already have a mortgage. This covers spending goals and large purchases (including
productive investments). The auto-plan never includes a loan. The suggested rate is built
from the client's own financing history, people like them (when the bank data has rates;
otherwise we say it doesn't), and a transparent creditworthiness score.
"""
from __future__ import annotations

from datetime import date

from pydantic import Field

from ..model import AssumptionBook, Debt, LeverImpact, OneOff, RecurringDelta, add_months, fixed
from ..swiss import fmt_chf
from .base import LeverContext, lever
from .primitives import Base, Estimate, _share, primitive


def annuity_payment(principal: float, annual_rate: float, term_months: int) -> float:
    """Fixed monthly installment for a fully amortising loan."""
    if term_months <= 0 or principal <= 0:
        return 0.0
    r = annual_rate / 12
    if r <= 1e-12:
        return principal / term_months
    growth = (1 + r) ** term_months
    return principal * r * growth / (growth - 1)


def remaining_after(principal: float, annual_rate: float, term_months: int, payments_made: int) -> float:
    """Balance after `payments_made` installments (0 = just drawn, before the first payment)."""
    if principal <= 0 or term_months <= 0 or payments_made <= 0:
        return max(principal, 0.0) if payments_made <= 0 else 0.0
    if payments_made >= term_months:
        return 0.0
    r = annual_rate / 12
    pmt = annuity_payment(principal, annual_rate, term_months)
    if r <= 1e-12:
        return max(0.0, principal - pmt * payments_made)
    growth = (1 + r) ** payments_made
    return max(0.0, principal * growth - pmt * (growth - 1) / r)


def _cfg(ctx: LeverContext) -> dict:
    return ctx.cfg.get("loan") or {}


def _spend_goal(ctx: LeverContext) -> bool:
    g = ctx.goal
    if g.type in ("home", "retirement"):
        return False
    if g.type == "target":
        return str(g.params.get("kind", "spend")) == "spend"
    return False


def creditworthiness(ctx: LeverContext) -> tuple[float, list[str]]:
    """0..1 score plus the factors, so the card can say why the rate sits where it does."""
    p = ctx.profile
    income = p.income.salary_net_monthly_avg + p.income.other_income_monthly
    housing = p.monthly("housing")
    financing = -sum(r.monthly_equivalent for r in p.recurring if r.active and r.category == "car_financing")
    dti = (housing + financing) / max(income, 1.0)
    emp = ctx.client.extra.get("employment_type")
    score, bits = 0.5, []
    if p.buffer_months >= 6:
        score += 0.15
        bits.append(f"cash cushion {p.buffer_months:.1f} months of costs (comfortable)")
    elif p.buffer_months >= 3:
        score += 0.05
        bits.append(f"cash cushion {p.buffer_months:.1f} months of costs (typical)")
    else:
        score -= 0.15
        bits.append(f"cash cushion {p.buffer_months:.1f} months of costs (thin)")
    if p.savings_rate >= 0.15:
        score += 0.15
        bits.append(f"savings rate {p.savings_rate:.0%} (strong)")
    elif p.savings_rate < 0:
        score -= 0.15
        bits.append(f"savings rate {p.savings_rate:.0%} (spending more than you earn)")
    else:
        bits.append(f"savings rate {p.savings_rate:.0%}")
    if dti > 0.40:
        score -= 0.15
        bits.append(f"housing and existing financing are {dti:.0%} of net income (high)")
    elif dti < 0.20:
        score += 0.05
        bits.append(f"housing and existing financing are {dti:.0%} of net income")
    else:
        bits.append(f"housing and existing financing are {dti:.0%} of net income")
    if emp == "employed":
        bits.append("employment looks steady")
    elif emp is None:
        bits.append("employment type not on file")
    elif emp == "self_employed":
        score -= 0.05
        bits.append("self-employed (lenders usually want a higher rate)")
    else:
        score -= 0.10
        bits.append(f"employment: {str(emp).replace('_', ' ')}")
    if financing > 0:
        score -= 0.05
        bits.append(f"you already pay {fmt_chf(financing)}/month in car financing")
    return max(0.15, min(0.92, score)), bits


def suggested_rate(ctx: LeverContext) -> tuple[float, list[dict], float]:
    """(rate, source rows for the Details drawer, credit score). Never invents a peer rate."""
    cfg = _cfg(ctx)
    base = float(cfg.get("unsecured_base", 0.069))
    lo, hi = float(cfg.get("unsecured_min", 0.049)), float(cfg.get("unsecured_max", 0.110))
    spread = float(cfg.get("rate_spread", 0.06))
    score, bits = creditworthiness(ctx)
    rate = max(lo, min(hi, base + (0.5 - score) * spread))
    band = "strong" if score >= 0.65 else "stretched" if score <= 0.35 else "mid"

    financing = [r for r in ctx.profile.recurring if r.active and r.category == "car_financing"]
    if financing:
        monthly = -sum(r.monthly_equivalent for r in financing)
        names = ", ".join((r.counterparty or r.merchant) for r in financing[:3])
        history = (f"You already pay {fmt_chf(monthly)}/month in car financing ({names}). "
                   f"Existing debt is a reason to expect a rate a bit above typical.")
    else:
        history = "No consumer-loan or leasing payments show up in your recent transactions."

    pop = ctx.services.get("population")
    typical = f"{lo:.1%}–{hi:.1%}"
    if pop is not None and getattr(pop, "available", False):
        key, seg = pop.segment(float(ctx.profile.age or 40), ctx.client.extra.get("employment_type"))
        n = int(seg.get("n_people", 0) or 0)
        who = key.replace("|", ", ") if key != "all" else "everyone in the data"
        peer = (f"People like you ({who}, {n} in the bank's data): this dataset has no observed consumer-loan "
                f"rates, so we do not pick a peer average. Typical advertised unsecured rates are {typical}.")
        peer_source = "population"
    else:
        peer = (f"People like you: no bank-wide loan-rate data in this environment. Typical advertised "
                f"Swiss unsecured rates are {typical}.")
        peer_source = "market_default"

    credit = (f"Apparent creditworthiness looks {band} ({score:.0%} on our 0–100 scale, not a SCHUFA/ZEK score). "
              f"{'; '.join(bits)}. That sits the suggested rate near {rate:.1%} (base {base:.1%}, range {typical}).")
    sources = [
        {"title": "Your history", "text": history, "source": "transactions"},
        {"title": "People like you", "text": peer, "source": peer_source},
        {"title": "Apparent creditworthiness", "text": credit, "source": "client_data"},
    ]
    return rate, sources, score


def make_loan(ctx: LeverContext, *, lever_id: str, title: str, amount: float, at: date,
              finances: str, label: str, rate: float | None = None, term: int | None = None,
              invest_return: float | None = None) -> LeverImpact | None:
    """Cash in at `at`, then a fixed installment. Off unless the client switches it on."""
    cfg = _cfg(ctx)
    min_p, max_p = float(cfg.get("min_principal", 3000)), float(cfg.get("max_principal", 80000))
    if amount < min_p:
        return None
    default_p = min(amount, max_p)
    a = ctx.book(lever_id)
    share = a.get("share", default_p / amount, label="Share of the expense to finance", unit="share",
                  source="market_default", low=0.1, high=1.0, step=0.05)
    principal = a.get("principal", round(amount * share, -2), label="Loan amount", source="market_default",
                      low=min_p, high=min(amount, max_p), step=500,
                      note=f"Swiss consumer loans are typically capped at {fmt_chf(max_p)}" if amount > max_p else None)
    principal = max(min_p, min(principal, max_p, amount))
    suggested, sources, _score = suggested_rate(ctx)
    rate = a.get("annual_rate", suggested if rate is None else rate, label="Suggested interest rate", unit="%/yr",
                 source="market_default" if rate is None else "llm_estimate",
                 low=float(cfg.get("unsecured_min", 0.049)), high=float(cfg.get("unsecured_max", 0.110)),
                 step=0.001, needs_confirmation=True,
                 note=("Suggested {rate:.1%}/year from your history, people like you, and apparent creditworthiness. "
                       "You can change it.").format(rate=suggested))
    term = int(a.get("term_months", term if term is not None else int(cfg.get("term_months_default", 48)),
                     label="Term", unit="months",
                     source="market_default", low=int(cfg.get("term_months_min", 12)),
                     high=int(cfg.get("term_months_max", 84)), step=6))
    term = max(int(cfg.get("term_months_min", 12)), min(int(cfg.get("term_months_max", 84)), term))
    pmt = annuity_payment(principal, rate, term)
    years = term / 12
    notes = [
        "This is a consumer loan. It stays off unless you switch this action on — we will not assume a loan.",
        f"Suggested rate {rate:.1%}/year. Total repay {fmt_chf(pmt * term)} over {years:.0f} years "
        f"(interest about {fmt_chf(pmt * term - principal)} on {fmt_chf(principal)}).",
        *(f"{row['title']}: {row['text']}" for row in sources),
    ]
    if invest_return is not None:
        verdict = ("below" if invest_return < rate else "above")
        notes.append(f"Borrowing to invest: the loan costs {rate:.1%}/year, the investment is expected to earn "
                     f"{invest_return:.1%}/year ({verdict} the interest). The return is uncertain, the interest is not.")
    if amount > max_p:
        notes.append(f"The expense is {fmt_chf(amount)}; we only offer to finance {fmt_chf(principal)} (typical consumer-loan cap).")
    return LeverImpact(
        lever_id=lever_id, title=title,
        description=(f"Borrow {fmt_chf(principal)} at a suggested {rate:.1%}/year for {years:.0f} years. "
                     f"Installment {fmt_chf(pmt)}/month. Off unless you switch it on."),
        group="structural", effort="high", confidence="estimated", product_trigger="loan", icon="banknote",
        one_offs=[OneOff(at=at, amount=fixed(principal), label=f"Loan payout: {label}")],
        recurring=[RecurringDelta(start=at, end=add_months(at, term - 1), monthly=fixed(-pmt), indexed=False,
                                  label=f"Loan installment ({rate:.1%})")],
        debts=[Debt(start=at, principal=principal, annual_rate=rate, term_months=term, label=f"Loan: {label}")],
        headline_monthly=round(-pmt, 2),
        side_effects=["You will owe this amount plus interest; remaining debt is marked on the chart.",
                      "A real lender will run its own credit check; this rate is a suggestion, not an offer."],
        assumptions=a.list(),
        details={"needs_agreement": True, "finances": finances, "title_key": "finance_with_loan",
                 "title_args": {"label": label}, "rate_sources": sources, "notes": notes,
                 "loan": {"principal": principal, "annual_rate": rate, "term_months": term, "installment": round(pmt, 2)}},
    )


@lever("finance_with_loan")
def finance_with_loan(ctx: LeverContext):
    if not _spend_goal(ctx):
        return None
    amount = float(ctx.goal.params.get("amount") or 0)
    at = ctx.target or ctx.start
    if at > ctx.start:
        at = add_months(at, -1)   # payout must be in cash at the goal-month snapshot (start of that month)
    label = ctx.goal.label
    return make_loan(ctx, lever_id=f"loan:goal:{ctx.goal.id}", title=f"Finance “{label}” with a loan",
                     amount=amount, at=at, finances="goal", label=label)


def companions(ctx: LeverContext, levers: list[LeverImpact]) -> list[LeverImpact]:
    """A separate loan action for a large cash purchase or investment on another lever (farm, equipment, fund, …)."""
    cfg = _cfg(ctx)
    min_p = float(cfg.get("min_principal", 3000))
    out = []
    for lv in levers:
        if lv.debts or lv.details.get("needs_agreement") or lv.product_trigger == "loan":
            continue
        if lv.group in ("life_event", "goal_change") or lv.lever_id == "invest_idle_cash":
            continue   # idle cash is money the client already has: borrowing to invest it makes no sense
        outs = [(o.at, -o.amount.mean(), None) for o in lv.one_offs if o.bucket == "cash" and o.amount.mean() <= -min_p]
        outs += [(i.start, i.once.mean(), i.expected_return) for i in lv.investments
                 if i.once is not None and i.from_bucket == "cash" and i.once.mean() >= min_p]
        if not outs:
            continue
        at, principal, ret = max(outs, key=lambda x: x[1])
        loan = make_loan(ctx, lever_id=f"loan:{lv.lever_id}", title=f"Finance “{lv.title}” with a loan",
                         amount=principal, at=at, finances=lv.lever_id, label=lv.title, invest_return=ret)
        if loan:
            out.append(loan)
    return out


def select_active(by_id: dict[str, LeverImpact], ids: list[str]) -> list[LeverImpact]:
    """Drop a companion loan whose purchase is not also on — otherwise it would be free cash."""
    have = set(ids)
    out = []
    for i in ids:
        lv = by_id.get(i)
        if lv is None:
            continue
        parent = lv.details.get("finances")
        if parent and parent != "goal" and parent not in have:
            continue
        out.append(lv)
    return out


class Loan(Base):
    principal: Estimate = Field(description="CHF borrowed (positive)")
    annual_rate: Estimate = Field(description="Yearly interest as a share (0.069 = 6.9%). Suggest from the client's "
                                  "history, people like them, and creditworthiness; never invent a peer rate.")
    term_months: int = 48
    in_months: int = 0


@primitive("loan", Loan, "An unsecured consumer loan the client must explicitly agree to as a separate action. "
           "Do not add this unless they said they want to borrow. Principal arrives as cash; they repay a fixed "
           "installment. Do not combine it with the purchase — the product already offers a separate finance action.")
def loan_primitive(p: Loan, ctx: LeverContext, lever_id: str, book: AssumptionBook) -> LeverImpact:
    at = add_months(ctx.start, p.in_months)
    principal = p.principal.read(book, "principal")
    r0 = p.annual_rate.value / (100.0 if abs(p.annual_rate.value) > 1.5 else 1.0)
    rate = _share(p.annual_rate, max(0.0, r0 - 0.04), r0 + 0.04).read(book, "annual_rate")
    term = max(12, int(p.term_months))
    loan = make_loan(ctx, lever_id=lever_id, title=p.title or "Take a loan", amount=principal, at=at,
                     finances="goal", label=p.title or "loan", rate=rate, term=term)
    if loan is None:
        return LeverImpact(lever_id=lever_id, title=p.title or "Take a loan", description=p.description,
                           assumptions=book.list(), details={"notes": ["Loan amount is below the consumer-loan minimum."]})
    loan.description = p.description or loan.description
    loan.side_effects = list(p.side_effects) + list(loan.side_effects)
    return loan
