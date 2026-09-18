# My Goal, My Plan: Build Plan

**Event:** Finnova hackathon (Swiss {ai} Weeks), Lenzburg, Fri 18 Sep 2026
**Case:** 6, Financial Stability Layer
**Budget:** prototype tonight; 6 h on the day (lunch included) to adapt, polish and pitch

> Numbers marked **(verify)** come from memory, not a checked source. Fill them into `config/*.yaml` tonight from official pages and don't hard-code them.

---

## 0. Ground rules for the design

1. **One adapter absorbs the real data.** Everything downstream reads a canonical schema, so tomorrow's surprise is contained in one file.
2. **Numbers never come from the LLM.** The LLM routes, asks, phrases and proposes *labelled* estimates. The engine computes.
3. **Every lever returns the same `LeverImpact` shape.** Teammate ideas become new levers or specialists, not rewrites.
4. **Every number has a source tag:** `transactions | user | market_default | llm_estimate`, shown in the UI.
5. **The demo path is sacred.** One persona, one goal, a ranked lever list, one free-text "what if". Everything else is a bonus.
6. The event is advertised as 12 hours; our budget is 6. Confirm the schedule at check-in.

---

## 1. Finnova's tech landscape and what it means for us

| What we know | Source | Implication for us |
|---|---|---|
| Front-office apps (Advisor Workbench, portal, Loan Advisory) run on managed OpenShift (VSHN/APPUiO) | VSHN case study | Ship a `Dockerfile`, a stateless service, env-var config. "OpenShift-ready" is a credible pitch line |
| The Finnova Open Platform includes an Integration Layer, SSO and an orchestration layer, also on OpenShift | VSHN case study | Pitch the engine as a **service on the Open Platform**, not a standalone app |
| API-first positioning; partner APIs listed on openbankingproject.ch (e.g. Client Overview API for 360° client data) | finnova.com, openbankingproject.ch | FastAPI with an auto-generated OpenAPI spec; mirror client / account / booking resource naming |
| Front office has an **Advisor Workbench** | VSHN case study | Second surface: the same levers become an advisor's conversation agenda plus product triggers. This answers the case's "cross-selling is reactive" point |
| Core likely Oracle + large legacy/PL-SQL estate; newer services likely Java | Industry knowledge, **not confirmed** | Don't imitate it; we're a sidecar that consumes bookings |
| Swiss standards: ISO 20022 camt.053/054 statements, OpenWealth API, SIX bLink | Industry knowledge (verify relevance) | The adapter should tolerate camt-like fields (booking/value date, BkTxCd, remittance info) |
| Swiss bank constraints: data residency, FINMA outsourcing rules, explainability | General | LLM behind an interface with a local-model option; transparent model, no black-box ML |

### Our stack

| Layer | Choice | Why |
|---|---|---|
| Engine | Python 3.12, numpy, pydantic v2, polars (or pandas) | Fast vectorised Monte Carlo; the team can read it |
| API | FastAPI | Free OpenAPI spec, matches the API-first story |
| UI | React + Vite + TypeScript + Tailwind + Recharts, served by FastAPI | Judges judge polish; live toggles need a real frontend |
| Debug UI | Streamlit page over the same engine | For non-frontend teammates, and a fallback demo |
| LLM | Provider-agnostic `LLMClient`: Claude by default (Sonnet for the agent, Haiku for categorisation); optional OpenAI-compatible local endpoint (vLLM or llama.cpp on the 3090) | The "client data never leaves the bank" story is a stretch goal |
| Packaging | Dockerfile + docker-compose | OpenShift-ready claim; no actual deployment |
| i18n | EN + DE string table | Aargau audience; DE labels are a cheap goodwill win |

---

## 2. Architecture

```
raw data (CSV/JSON/camt/?)
        │
   [Adapter]  ← the only thing rewritten tomorrow
        │  canonical: Client, Account, Booking, Position
   [Categoriser]  rules → merchant dict → LLM fallback (cached)
        │
   [Profile builder]  baseline flows, recurring, income, buffer, asset hints, opaque flows
        │
   [Engine]  monthly Monte Carlo ◄── [Goals]  home | retirement | target-by-date
        ▲
   [Levers]  primitives ◄── specialists: car, KVG health (+ insurer interface), oddball agent
        │
   [Explainer]  templated text; LLM only rephrases
        │
   [API]  FastAPI /profile /goals /levers /simulate /whatif
        │
   [UI]  client view (+ advisor view if time)
```

---

## 3. Canonical data model

```python
class Booking(BaseModel):
    id: str
    account_id: str
    booking_date: date
    value_date: date | None
    amount: Decimal              # signed, account currency
    currency: str = "CHF"
    text: str                    # raw description / remittance info
    counterparty: str | None
    counterparty_iban: str | None
    mcc: str | None              # card merchant category if present
    bank_category: str | None    # if the data already has one, trust it first
    # derived
    category: str | None = None
    category_source: Literal["bank", "rule", "merchant", "llm", "user"] | None = None
    recurring_group: str | None = None

class Account(BaseModel):
    id: str; client_id: str
    type: Literal["private", "savings", "3a", "securities", "mortgage", "card", "other"]
    balance: Decimal; currency: str

class Position(BaseModel):         # securities, if provided
    account_id: str; name: str; value: Decimal; asset_class: str

class Client(BaseModel):
    id: str; birth_year: int | None; canton: str | None
    household: dict | None          # partner, kids, if provided
    goals: list[GoalSpec] = []      # if the data ships goals, use them
```

Category taxonomy (about 20, flat): `income_salary, income_other, housing, utilities, health_premium, health_costs, insurance_other, taxes, groceries, restaurants, transport_public, transport_car, car_financing, subscriptions, leisure_hobby, travel, childcare, shopping, savings_3a, investments, transfers_p2p, cash, fees, unexplained`.

---

## 4. Profile builder

- **Recurring detection:** same normalised counterparty, amount within ±10%, period in {7, 14, 30, 91, 365} ±3 days, at least 3 occurrences. Annual bills (car tax, Serafe, some premiums) matter: don't miss the 365-day period.
- **Baseline flows:** per category, median of the last 12 months, split into fixed (recurring) and variable.
- **Income:** detect salary (largest regular inflow), 13th month salary, volatility, irregular side income.
- **Buffer:** liquid assets ÷ fixed monthly costs, in months.
- **Opaque flows:** TWINT P2P, cash withdrawals and lump credit-card payments go to an explicit "unexplained" bucket and are shown honestly ("CHF 620/month we can't see into").
- **Asset hints:** car (fuel, leasing, car insurance, road traffic office), property (mortgage interest), 3a contributions, securities, boat (mooring), hobby merchants.
- **Output:** a `Profile` object plus a one-screen "where you stand" summary.

---

## 5. Engine

**Mechanics**
- Monthly steps; N = 2,000 paths; vectorised numpy. Target under 150 ms per scenario so toggles feel live. Cache the baseline.
- **State:** cash, invested, 3a, pillar 2 (deterministic projection), debts.
- **Stochastic inputs:** asset returns (lognormal per asset class), inflation, income shocks (job-loss probability and duration), expense noise, lever shocks (e.g. health costs).
- **Behavioural haircut:** behavioural levers decay over time, e.g. `effect × (0.5 + 0.5·e^(−t/12))`. It's an explicit, user-visible assumption.
- **Config:** `config/market.yaml` (returns, volatilities, inflation, cash rate). Defaults are labelled `market_default`.

**Outputs per goal**
- P(success by target date), shown as "in 7 of 10 futures".
- Median achievable date plus a P10–P90 band.
- **Gap:** extra CHF/month needed to reach P ≥ 70% by the target date (bisection).
- **Decision deadline** (answers "when does it become critical"): the latest start date for the best feasible lever set that still reaches P ≥ 70%. Wording: *"Start by March 2027 and you still make 2031."*

### Goals

**Home purchase.** Two constraints plus accumulation:
- **Equity:** at least 20% of price. At most 10 percentage points may come from pillar 2 (at least 10% "hard" equity). Buying costs are about 5% (verify, canton-dependent).
- **Affordability:** (imputed interest 5% + maintenance 1% of price + amortisation of the 2nd mortgage down to 65% LTV within 15 years) ÷ gross income ≤ 33% (verify; lender-dependent).
- A pillar 2 withdrawal feeds a reduced retirement projection. This is the cross-goal effect the case asks about.

**Retirement / early retirement.** Simplified: required capital = (target spend − AHV − BVG annuity) × years in retirement, discounted. AHV maximum pension, 13th AHV payment, and the BVG conversion rate go in `config/pension.yaml` (verify). Early retirement means an income gap, reduced AHV, and a pillar 2 capital/annuity choice. P1 at most.

**Target by date.** A generic amount-by-date goal: trip, sabbatical, wedding, car.

**Family** isn't a savings goal; it's a **lever bundle**: childcare costs, a bigger apartment, parental leave income dip, part-time. Model it that way and it reuses everything.

---

## 6. Lever contract

```python
class Assumption(BaseModel):
    key: str; label: str
    value: float; low: float | None; high: float | None
    unit: str
    source: Literal["transactions", "user", "market_default", "llm_estimate"]
    editable: bool = True

class LeverImpact(BaseModel):
    lever_id: str
    title: str                              # "Sell your car"
    one_offs: list[OneOff]                  # date, amount (dist)
    recurring: list[RecurringDelta]         # start, end, monthly delta (dist)
    shocks: list[Shock]                     # annual prob, severity dist
    income_changes: list[IncomeDelta]       # flows through taxes / pension
    allocation_changes: list[AllocationDelta]
    assumptions: list[Assumption]
    side_effects: list[str]                 # "+25 min commute/day"
    confidence: Literal["structural", "behavioural", "estimated"]
    effort: Literal["none", "low", "medium", "high"]
    product_trigger: str | None             # "mortgage", "3a", "investment_plan" (advisor view only)
```

Distributions are a small tagged union (`fixed | normal | lognormal | uniform | empirical`) that the engine samples.

### Primitives (the long tail)

| Primitive | Parameters | Examples |
|---|---|---|
| `recurring_change` | category/merchant, delta, start, end | Subscriptions, hobby spend, rent |
| `asset_dispose` | sale value (dist), time to sell, running costs removed | Car, boat, Warhammer army |
| `asset_acquire` | price, financing, running costs, depreciation | Car, e-bike, home |
| `income_change` | delta %, start, end, pension/tax pass-through | Part-time, sabbatical, raise |
| `one_off` | date, amount | Wedding, renovation |
| `shock` | probability, severity | Health, job loss, repair |
| `substitute` | remove X, add basket Y | Car → transit |
| `reallocate` | from, to, amount/monthly | Cash → ETF plan, 3a top-up |
| `goal_change` | amount, date, location | Cheaper home, later date |

**Ranking.** Sort by impact (months gained, or ΔP) and group into: no lifestyle cost / structural / behavioural / change the goal. Show effort and confidence badges.

**Cheap built-in levers:** idle cash → invested, 3a maximisation (tax saving at an estimated marginal rate, flagged), subscription cleanup, discretionary cut (behavioural).

---

## 7. Specialists

### 7.1 Car (concrete)

**Detect** from transactions: fuel, leasing, car insurance, vehicle tax, parking, service, road tolls/vignette.

**Estimate km/year** = fuel CHF ÷ fuel price ÷ consumption. Defaults: ~CHF 1.80/l, 7 l/100 km (verify; editable, source-tagged).

**Sell the car** = `asset_dispose` + `substitute`:
- Sale value: user input, or a depreciation curve (default ~12%/yr, flagged).
- Removed: leasing or financing, insurance, tax, parking, service, fuel.
- Added basket: the cheapest option across these scenarios.
  - (a) GA
  - (b) Halbtax + point-to-point tickets
  - (c) Halbtax + car-sharing for the X km/year the user still needs by car

  The one question for the user is a slider: *"How many of today's car km would still need a car?"*
- Side effects: travel-time delta as a rough multiplier, shown as text.
- `prices.yaml` (fill from sbb.ch and the car-sharing tariffs tonight): GA and Halbtax prices, average CHF/km for point-to-point, car-sharing hourly and km rates.

**Buy a car** is the mirror: `asset_acquire` plus the share of transit spend replaced (user slider).

**Roadmap slide:** a door-to-door trip optimiser replaces the slider with real trip-level substitution.

### 7.2 Health: KVG deductible (basic) + insurer integration

**Rules** (`config/kvg.yaml`, verify all):
- Adult deductibles 300 / 500 / 1000 / 1500 / 2000 / 2500.
- Co-pay 10% above the deductible, capped at CHF 700/year for adults; hospital contribution ~CHF 15/day.
- Maximum premium discount for a higher deductible is regulated (about 70% of the extra risk taken, i.e. ≤ CHF 1,540 at 2,500).
- Deadlines: insurer switch or lower deductible by 30 Nov; raising the deductible with the same insurer by 31 Dec.

**Annual cost for deductible d and gross medical cost C:**

```
cost(d, C) = 12·premium(d) + min(C, d) + min(0.1·max(C − d, 0), 700)
```

Break-even between 300 and 2,500 lands around C ≈ CHF 2,000/year, and the worst-case downside is bounded (about CHF 2,200 minus the premium saving). That's the pitch sentence.

**Cost model (past ≠ future):**
- Estimate gross annual costs from bills and reimbursements. Caveat: with *tiers garant* the client pays and gets reimbursed (both visible); with *tiers payant* only the client's share is billed. Surface this as "partially visible".
- Sample next year's C from a mixture: P(C = 0) and a lognormal for positive costs. Shrink the client's history toward an age-band prior with weight `n/(n+3)`.
- Report E[cost] per deductible **and** the worst case. Recommend on expected cost unless the buffer is below one worst case.

**Integration (the "insurer-side agent"):**

```
InsurerQuoteService.quote(age_band, canton, premium_region, model, deductible, accident_cover) -> monthly_premium
```

- Tonight: a mock with a small premium table.
- Pitch: this is the seam where an insurer's agent or a comparison service plugs in. The bank consumes the projection; supplementary insurance (VVG, with underwriting) stays insurer-side.
- Timely hook: next year's premiums are typically announced by FOPH in late September (verify). "Your deductible check for 2027" is a natural autumn campaign.

**Output:** a `reallocate`-style lever ("switch to 2,500: +CHF X/yr expected, worst year −CHF Y") with the shock attached.

### 7.3 Oddball agent (Warhammer, boat, Tibetan cheese side business)

**Tools exposed to the LLM:**
- `search_transactions(query, date_range)` → aggregated matches (merchant, count, sum, cadence)
- `get_profile_summary()`
- `ask_user(question, options | numeric_range)` → at most 2 questions
- `propose_lever(primitive, params, assumptions[])` → pydantic-validated; rejected if any number lacks an `Assumption`
- `evaluate(levers[])` → goal deltas from the engine

**Rules** (system prompt):
- Pick primitives, never invent formulas.
- Every estimate is tagged `llm_estimate` with a low/high range.
- At most 6 tool steps.
- If it can't model the item reliably, say what's missing instead of guessing.

**Worked examples** to test tonight:
- **Warhammer.** `asset_dispose` (resale value range, ask the user for rough army size or purchase total; the haircut is an estimate) + `recurring_change` (hobby merchant spend → 0, or reduced).
- **Boat.** `asset_dispose` + removed seasonal recurring costs (mooring, insurance, maintenance, winter storage); sale takes months, so `time_to_sell` matters.
- **Tibetan cheese side business.** An `income_change` stream with revenue minus input costs, volatile; self-employed social contributions and income tax at the marginal rate (flag as estimate). Scenarios: scale up (one-off investment + higher net) or stop (lose net, free up time).

**UI:** the agent's result renders as a normal lever card, with amber sliders for `llm_estimate` assumptions.

---

## 8. Explainer and UI

### Client view (one screen, under a minute)

1. **Where you stand:** free cash flow per month, buffer in months, 12-month trend arrow, and the unexplained share.
2. **Goal card:** *"Home in Baden: on track for 2034, you want 2031."* Gap: *"CHF 540/month short"*. Main driver in one sentence. The decision deadline.
3. **Levers:** grouped and ranked toggles; the goal date and fan chart update live. Badges show effort and confidence.
4. **"What if…" box:** routes to a specialist or the oddball agent.
5. **"Why?" drawer:** each number shows its assumptions and sources, with editable sliders.

### Advisor view (P1)
- The same data framed as a conversation agenda: top 3 levers, open questions (opaque flows, missing data), and product triggers (mortgage pre-check, 3a, investment plan).
- Visually separate from the client's advice.

### Wording rules
- Dates over probabilities; CHF/month over totals.
- "7 of 10 futures" instead of "70%".
- No jargon without a tooltip.
- Never "you should"; use "one option is".

---

## 9. Synthetic data (tonight)

**Generator:** `scripts/gen_data.py --persona lena --months 36 --seed 1`, writing CSV in a camt-ish shape plus a JSON client file.

### Personas

| Persona | Situation | Goal | Levers it should surface |
|---|---|---|---|
| **Lena, 31, Zurich** | Single, CHF 105k salary, car (leasing), 300 deductible with ~0 medical costs, CHF 45k idle cash, Netflix/Spotify | Apartment by 2030 | Idle cash → invest, deductible, sell car, 3a. Netflix ranks last (the demo punchline) |
| **Marco & Sara, 36/34, Aargau** | 1 child, second planned, two cars, one part-time income | Home + second child | Family lever bundle, pillar 2 withdrawal hurting retirement (cross-goal) |
| **Urs, 52, Lucerne** | High income, boat, Warhammer, small Tibetan cheese side income | Retire at 60 | Oddball agent, early retirement gap |

### Realism and mess to include (so the adapter is battle-tested)
- German booking texts: "Zahlung", "Gutschrift", "TWINT *", "Einkauf Migros", "Lastschrift".
- Salary with a 13th month; annual bills (vehicle tax, Serafe, tax instalments).
- Health bills from doctors and pharmacies, plus insurer reimbursements with a delay.
- TWINT P2P, cash withdrawals, lump credit-card payments.
- Duplicate-looking bookings, a refund, one missing month, amounts with rounding noise.

---

## 10. Tonight's checklist

The full list is about 8 hours. Do P0 first (about 4 h with Claude Code), then P1 as time allows.

| # | Task | Priority | Est. |
|---|---|---|---|
| 1 | Repo scaffold, Dockerfile, FastAPI skeleton, `LLMClient` interface | P0 | 20m |
| 2 | Generator + Lena persona | P0 | 45m |
| 3 | Adapter + canonical model + rule/merchant categoriser | P0 | 40m |
| 4 | Profile builder | P0 | 40m |
| 5 | Engine + home + target-by-date goals, gap and decision deadline | P0 | 60m |
| 6 | Lever contract, primitives, 4 cheap levers, ranking | P0 | 30m |
| 7 | UI single screen with live toggles (Streamlit first if short on time) | P0 | 60–90m |
| 8 | KVG specialist + mock quote service | P1 | 40m |
| 9 | Oddball agent + the 3 worked examples | P1 | 60m |
| 10 | Car specialist + `prices.yaml` filled from official pages | P1 | 45m |
| 11 | Other personas, advisor view, retirement goal, DE strings | P2 | — |
| 12 | Pitch skeleton, architecture card, screenshots | P0 | 20m |

**Definition of done tonight:** `docker compose up` shows Lena's screen; toggling levers moves the date; one free-text what-if works end to end.

---

## 11. Day-of schedule (6 h)

| Time | Activity |
|---|---|
| 0:00–0:20 | Team intro. Present the prototype as a *proposal* plus the architecture card; invite ideas as new levers, specialists or goals. Assign roles: data/adapter, engine/levers, UI, agent + pitch |
| 0:20–1:00 | **Data recon:** load real data, run the §12 checklist, write the adapter, pick the demo client(s) from the real data |
| 1:00–2:30 | Adapt: categoriser rules for real merchants, profile sanity check, recalibrate defaults, one teammate feature |
| 2:30–3:00 | Lunch + full run-through on real data |
| 3:00–4:15 | Polish the demo path, build the pitch deck, advisor view if cheap |
| 4:15–4:45 | Bug bash; record a fallback screen video of the demo |
| **4:45** | **Feature freeze** |
| 4:45–5:30 | Rehearse the pitch 3×, timed |
| 5:30–6:00 | Buffer, submission |

---

## 12. Assumption checklist for the real data

- [ ] Format (CSV/JSON/XML/DB/API)? Encoding, delimiter, decimal separator, date format?
- [ ] Bookings only, or also balances, positions, 3a, mortgage, pension data?
- [ ] Time span and granularity? Enough for annual bills (≥ 13 months)?
- [ ] Is a category or MCC already present? Does it look trustworthy?
- [ ] Counterparty name/IBAN separate from the text, or buried in it?
- [ ] Client master data: age, canton, household, income?
- [ ] Are goals included in the data, or do we collect them in the UI?
- [ ] How many clients? One demo persona or many (a batch "triggers" view for the bank)?
- [ ] Language(s) of the booking texts?
- [ ] Card transactions itemised or lump sums? TWINT visible?
- [ ] Health bills/reimbursements visible? Car-related spend visible?
- [ ] Anything that breaks the recurring detector (irregular salary, multiple accounts)?
- [ ] LLM/API usage allowed with this data? Any provided model endpoint?

---

## 13. Pitch skeleton (~3 min; 60 s version = beats 1, 3, 4, 6)

1. **Hook:** *"Will my money be enough for what matters to me?"* Banking apps explain the past; nobody explains the future.
2. **Lena, where she stands:** one glance.
3. **Goal card:** "2034, not 2031; CHF 540/month short; start by March 2027."
4. **Aha:** the ranked levers. Cancelling Netflix is last; idle cash, deductible and car are first. Toggle, and the date moves live.
5. **Generality:** type *"What if I sell my Warhammer collection?"*; the agent builds a lever with transparent, editable estimates.
6. **Bank value:** scalable advice for every client, not just affluent ones; the advisor view turns levers into conversations and product triggers (mortgage, 3a, investing); it runs as an OpenAPI service on the Open Platform with the LLM swappable for a Swiss-hosted model.
7. **Trust:** every number shows its source; the LLM never invents figures.

---

## 14. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Real data is thin (no categories, few months) | Rule categoriser + LLM batch labelling; synthetic top-up clearly labelled "demo" |
| Real data lacks goals or client info | Goal wizard in the UI (3 questions) |
| LLM API unavailable or disallowed | Oddball agent falls back to a primitive picker form; everything else is LLM-free |
| Engine too slow for live toggles | Fewer paths (500) for interaction, 2,000 for the final number |
| Team wants a different angle | Engine + lever contract survive; swap the goal or specialist |
| Demo breaks on stage | Recorded video from 4:45 |

---

## 15. Repo layout

```
mygoal/
  adapters/        synthetic.py, realdata.py (tomorrow)
  model/           canonical.py, levers.py, goals.py
  categorise/      rules.yaml, merchants.yaml, llm.py
  profile/         builder.py, recurring.py
  engine/          simulate.py, solve.py (gap, deadline)
  levers/          primitives.py, builtin.py, ranking.py
  specialists/     car.py, kvg.py, insurer_quote.py, oddball_agent.py
  explain/         templates.py, i18n/{en,de}.yaml
  api/             main.py
  llm/             client.py (anthropic | openai-compatible local)
config/            market.yaml, pension.yaml, kvg.yaml, prices.yaml, mortgage.yaml
scripts/           gen_data.py
web/               React app
tests/             golden tests: Lena's baseline date, KVG break-even, car basket
Dockerfile, docker-compose.yml, README.md
```

---

## Sources
- VSHN case study, Finnova on APPUiO Managed OpenShift: https://www.vshn.ch/en/success-stories/finnova/
- Finnova homepage (hackathon, API-first): https://www.finnova.com/
- Finnova Client Overview partner API: https://www.openbankingproject.ch/en/catalog/apis/vendor/finnova-client-overview/
