# My Goal, My Plan: Financial Stability Layer

Finnova hackathon, case 6. From account data to "will my money be enough for what matters to me?":
where you stand, how realistic the goal is, how big the gap is, when it becomes critical, which options help
most, and how one decision moves your other goals.

**Design rules** (see `prototype-plan.md` §0):
1. One adapter absorbs the real data. Everything downstream reads the canonical model.
2. Numbers never come from the LLM. It routes, asks and proposes *labelled* estimates; the engine computes.
3. Every lever returns the same `LeverImpact` shape. New ideas become levers, specialists or goals, not rewrites.
4. Every number carries a source (`transactions | client_data | user | market_default | llm_estimate`) and is editable in the UI.

---

## Quick start

```bash
uv sync --all-extras                      # Python 3.12 deps (+ anthropic, openai, streamlit)
uv run python scripts/gen_data.py --all   # synthetic personas -> data/synthetic/<id>/
uv run pytest                             # golden tests (~10 s, no LLM needed)

# API + built UI on http://localhost:8080  (OpenAPI docs at /docs)
(cd web && npm install && npm run build)
uv run uvicorn mygoal.api.main:app --port 8080 --reload

# UI dev server with hot reload on http://localhost:5173 (proxies /api to :8080)
(cd web && npm run dev)

# Debug page for non-frontend work (same service layer)
uv run --extra debug-ui streamlit run scripts/debug_ui.py

# Container (OpenShift-style: non-root, one port, env config)
docker compose up --build        # picks up .env automatically
# or: podman build -t mygoal . && podman run -p 8080:8080 --env-file .env mygoal
```

**LLM (optional).** `LLM_PROVIDER=auto` uses Claude when `ANTHROPIC_API_KEY` (or an `ant auth login` profile) is
present, else the OpenAI cloud API when `OPENAI_API_KEY` is set (cheaper than Claude's fast model), else a local
OpenAI-compatible server at `OPENAI_BASE_URL` (LM Studio, vLLM, llama.cpp) if it answers, else none. Without an
LLM everything still works; free-text what-ifs use the rules agent. Force one with `LLM_PROVIDER=anthropic|openai|openai_compat`.
Models: `config/app.yaml` -> `llm` (agent `claude-sonnet-5`, fast `claude-haiku-4-5`, OpenAI cloud `gpt-5.6-luna`).
OpenAI cloud runs with `reasoning_effort: none` because gpt-5.x rejects function tools on chat completions otherwise
(`OPENAI_REASONING_EFFORT=""` for non-reasoning models). LLM failures are logged as `mygoal.agent` warnings.

---

## Architecture

```
raw data (CSV / Excel / JSON / camt-like)
      │  adapters/            mapping YAML or adapter class        <- the only thing rewritten for real data
      ▼
canonical model               model/canonical.py: Client, Account, Booking, Position
      │  categorise/          internal -> bank -> rules.yaml -> merchants.yaml -> MCC -> (LLM) -> fallback
      ▼
profile/                      recurring bills, income (13th), flows by category, buffer, opaque flows, asset hints
      │
      ▼  engine/baseline.py + engine/market.py (every number via AssumptionBook, editable)
engine/simulate.py            monthly Monte Carlo: cash, invested, 3a, pillar 2; inflation, returns, house prices,
      ▲                       job loss, spending noise; common random numbers (stable toggles, fair comparisons)
      │  LeverImpact[]        model/levers.py: one-offs, recurring deltas, shocks, income, allocations,
      │                       withdrawals, goal changes, assumptions, side effects, product trigger
levers/ builtin + primitives  specialists/ car, KVG (+ InsurerQuoteService), family      agent/ what-if (LLM or rules)
      │
goals/ home, target, retirement  -> engine/solve.py: P(success), date band, gap (bisection), decision deadline,
      │                                               ranking, greedy suggested plan, cross-goal effects
explain/                      templated EN/DE texts and "main driver" sentences (i18n/*.yaml)
      │
service.py  ──  api/main.py (FastAPI)  ──  web/ (React + Vite + Tailwind + Recharts)
            └─  advisor.py (agenda, open questions, product triggers)   └─ scripts/debug_ui.py (Streamlit)
```

| Question from the case | Where it's answered |
|---|---|
| Where do I stand today? | `profile/builder.py` -> `service.overview` -> stand tiles + spending card |
| How realistic is my goal? | `engine/solve.py` `Planner.outcome`: "likely Jun 2034, 0 of 10 futures by Jun 2031" |
| How big is the gap, when does it become critical? | `gap_monthly` (CHF/month for 7 of 10 futures), `deadline` ("start by May 2027") |
| What would need to change? | `rank` (months sooner per lever) + `auto_plan` (smallest plan that gets there) |
| How does one decision affect other goals? | goal `commitment()` + `service.cross_goal` ("buying in 2031 moves retirement from 60 to 62") |
| Explain the main drivers | `explain/drivers.py` (binding constraint, savings rate, biggest cost, idle cash, opaque flows) |
| Bank value: structured triggers | `advisor.py` (mortgage pre-check timing and volume, 3a, investment plan, partner referral) |

---

## Recipes: changing things without rewriting things

**Plug in tomorrow's real data.** `uv run python scripts/inspect_data.py <file>` shows delimiter, encoding,
column fill, date and number formats. Then either copy `mygoal/adapters/mappings/camt_flat.yaml` to
`mappings/realdata.yaml` and fill in the column names (supports signed / credit-debit indicator / split columns,
decimal comma, `1'234.50`, several date formats), and run with
`MYGOAL_DATA_SOURCE=realdata MYGOAL_DATA_DIR=data/real`; or write a new class with `@register_adapter("name")`
(see `adapters/realdata.py`). Unknown client fields can stay `None`: gross income and pillar 2 get estimated and
flagged "please confirm". If the data has its own categories, map them in `categorise/bank_categories.yaml`
(`map: {their_label: our_category}`). They're trusted before our rules.

**Add a lever** (any module under `mygoal/levers/` or `mygoal/specialists/`):
```python
@lever("sell_second_home", goal_types={"home", "retirement"})
def sell_second_home(ctx: LeverContext):
    hint = ctx.profile.hint("holiday_home")
    if not hint:
        return None
    a = ctx.book("sell_second_home")      # user edits from the "Why?" drawer arrive here automatically
    value = a.get("sale_value", 400_000, label="Sale value", source="market_default", low=300_000, high=500_000,
                  needs_confirmation=True)
    return LeverImpact(lever_id="sell_second_home", title="Sell the holiday flat", group="structural", effort="high",
                       one_offs=[OneOff(at=add_months(ctx.start, 6), amount=triangular(0.9 * value, value, 1.05 * value))],
                       recurring=[RecurringDelta(start=add_months(ctx.start, 6), monthly=fixed(hint.monthly_cost))],
                       assumptions=a.list())
```
It is ranked, planned, explained, toggled and shown in the UI with no other change.

**Add a specialist.** A module with a `@hint_detector` (what it detects in bookings), one or more `@lever`s,
and optionally a `@service` interface with a mock (see `specialists/kvg.py` + `insurer_quote.py`: the seam where
an insurer's quote agent plugs in; choose an implementation with `MYGOAL_SERVICE_INSURER_QUOTES=<impl>`).

**Add a goal type.** A class with `@register_goal("type")`, a pydantic `Params`, `evaluate()` returning
`feasible / have / need` per month and path, and `commitment()` describing what achieving it does to the household
(used for cross-goal effects). See `goals/target.py` (30 lines).

**Teach the what-if agent.** Vocabulary and intents live in `agent/keywords.yaml` (EN/DE synonyms, specialist
routing). New building blocks: `@primitive(...)` in `levers/primitives.py`. Its schema becomes an LLM tool
option and a fallback form (`GET /api/primitives`) automatically.

**Add an explanation.** `@driver("name")` in `explain/drivers.py`; wording in `explain/i18n/{en,de}.yaml`.

**Change a number.** `config/*.yaml`. Values marked `(verify)` were typed from memory, check before the pitch.
Global assumptions are also editable live in the UI ("Assumptions" link) and via `overrides.global` in the API.

**Plugins outside the repo.** `MYGOAL_PLUGINS=teammate_pkg.levers,teammate_pkg.goals` imports extra modules at startup.

**Swap the UI or the web framework.** Everything goes through `mygoal/service.py`; FastAPI is ~150 lines of glue.
The React app only talks to `/api` (typed in `web/src/api.ts`).

---

## API

| Method | Path | What |
|---|---|---|
| GET | `/api/clients` | available clients |
| GET | `/api/clients/{id}/overview?lang=` | where you stand, spending, hints, goals with status, data notes |
| POST | `/api/clients/{id}/plan` | `{goal_id, active[], overrides{global|lever_id: {key: value}}, lang}` -> outcomes, fan chart, gap, deadline, ranked levers, plan, drivers, texts, assumptions |
| POST | `/api/clients/{id}/cross-goal` | same body -> effects on other goals (slower, fetched after the plan) |
| PUT/DELETE | `/api/clients/{id}/goals/{goal_id}` | goal wizard |
| POST | `/api/clients/{id}/whatif` | `{text, goal_id, lang}` -> question / lever / unsupported |
| POST | `/api/whatif/{session}/answer` | `{answer}` |
| GET | `/api/clients/{id}/advisor?goal_id=` | advisor agenda and product triggers |
| GET | `/api/primitives`, `/api/meta`, `/api/i18n/{lang}` | schemas, LLM status, strings |

---

## Demo path (Lena, 31, Zurich)

1. **Where you stand:** keeps CHF 914/month (12%), 11 months of cushion, CHF 762/month we can't see into.
2. **Goal:** apartment near Winterthur, CHF 540k, June 2031 -> *likely Jun 2034; CHF 660/month short;
   start by May 2027 and you still make it.* Driver: the bank wants ~CHF 127k of own funds by then; she'd have ~96k.
3. **Levers:** pillar 2 (with a retirement trade-off), return the car when the lease ends, cheaper home, 3a,
   idle cash, deductible... Netflix last. "Use suggested plan" (car + 3a) -> 8-9 of 10 futures, the date moves live.
4. **What if I sell my Warhammer collection?** -> finds Games Workshop spending (~CHF 65/month), asks the sale
   value, builds a lever with labelled, editable estimates.
5. **Why? drawer on the deductible:** expected cost and worst year per deductible, break-even ~CHF 2,000/year.
6. **Advisor view:** agenda, questions to confirm (km driven, lease end, tax rate), mortgage pre-check in mid-2030
   (CHF 432k volume), 3a before 31 Dec, investment plan, health insurance partner referral.

Other personas: **Marco & Sara** (Baden, one child: house vs. second child, pillar 2 vs. retirement, two cars)
and **Urs** (Lucerne, 52: retire at 60 vs. likely 64; boat, Warhammer army, cheese side business for the what-if agent).

---

## Known simplifications (say them before a judge does)

- Taxes are a spending category from the bookings; only 3a savings, side income and part-time get a marginal-rate
  estimate. No full tax engine.
- Retirement is a capital-gap model (AHV scaled by income, pillar 2 annuity, private capital to life expectancy).
- Home affordability uses the standard 5% / 1% / 1/3 rules; buying costs per canton are rough.
- Behavioural savings fade (`market.behavioural_haircut`); variable spending grows with wages, fixed costs with prices.
- Credit-card lump payments, cash and TWINT are shown as opaque, not guessed.
- What-if sessions and goal edits are in memory (fine for a demo, one replica).
