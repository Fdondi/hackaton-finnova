# Developer notes: My Goal, My Plan

Implementation notes for the Finnova hackathon prototype (case 6); the user-facing overview is in the README. From account data to "will my money be enough for what matters to me?":
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
uv run python scripts/prep_testdata.py    # organisers' testdata (1.2 GB CSV) -> data/testdata/ parquet + population stats (~40 s)
uv run python scripts/pick_demo_clients.py  # rank story-rich demo clients with the engine -> data/testdata/shortlist.json (~2 min)
uv run pytest                             # golden tests on the synthetic personas (~10 s, no LLM needed)

# API + built UI on http://localhost:8080  (OpenAPI docs at /docs)
(cd web && npm install && npm run build)
uv run uvicorn mygoal.api.main:app --port 8080 --reload

# UI dev server with hot reload on http://localhost:5173 (proxies /api to :8080)
(cd web && npm run dev)

# Debug page for non-frontend work (same service layer)
uv run --extra debug-ui streamlit run scripts/debug_ui.py

# Container (OpenShift-style: non-root, one port, env config)
docker compose up --build        # picks up .env automatically
# or: podman build --format docker -t mygoal . && podman run -p 8080:8080 --env-file .env mygoal
#     (--format docker keeps the HEALTHCHECK; package downloads are cached between builds)
```

**Investments.** The `invest` primitive (and "Put idle cash to work") puts money into its own pot in every simulated
future, with its own expected return and volatility in % (editable in Details): the committed money is tracked
separately from the rest of the portfolio, moves with the market draws scaled to its volatility, counts as invested
money for goals and can fund a home purchase. The global portfolio return and volatility are editable on the facts page.

**Loans.** Borrowing is always a separate action that stays off until the client switches it on, and the auto-plan never
includes one (`mygoal/levers/loan.py`). A spending goal gets "Finance it with a loan", and so does any large cash purchase
or investment from the what-if box ("Finance «Index fund» with a loan"); the loan is dropped when the thing it finances is
off. The suggested rate comes from the client's own financing history, people like them and a creditworthiness score
(never an invented peer rate), and every figure is editable. The card shows the installment and total interest, and for an
investment it sets the loan's rate against the expected return. The main chart marks the payout and draws the remaining
debt as a line. Homes (mortgage) and "put idle cash to work" are not offered a consumer loan.

**Languages.** UI strings live in `mygoal/explain/i18n/<lang>.yaml`; the engine writes English and
`mygoal/explain/translate.py` translates its labels and sentences at the API boundary (`labels`, `label_patterns`,
`unit_words` in the same YAML). AI-suggested goals are translated once per language.

**LLM (optional).** `LLM_PROVIDER=auto` uses Claude when `ANTHROPIC_API_KEY` (or an `ant auth login` profile) is
present, else the OpenAI cloud API when `OPENAI_API_KEY` is set (cheaper than Claude's fast model), else a local
OpenAI-compatible server at `OPENAI_BASE_URL` (LM Studio, vLLM, llama.cpp) if it answers, else none. Without an
LLM everything still works; free-text what-ifs use the rules agent. Force one with `LLM_PROVIDER=anthropic|openai|openai_compat`.
Models: `config/app.yaml` -> `llm` (agent `claude-sonnet-5`, fast `claude-haiku-4-5`, OpenAI cloud `gpt-5.6-luna`).
OpenAI cloud runs with `reasoning_effort: none` because gpt-5.x rejects function tools on chat completions otherwise
(`OPENAI_REASONING_EFFORT=""` for non-reasoning models). LLM failures are logged as `mygoal.agent` warnings.

---

## The client flow (whiteboard mock `mock.jpg`, `structure.md`)

1. **Goals** (`web/src/pages/GoalsPage.tsx`): "Tell us your financial goal". Suggestions sit as desaturated ovals in
   the goal box (confirm ✓ / edit ✎ / delete ✕): rules on the data first, then the LLM's personal ideas
   (`mygoal/agent/goal_assistant.py`, `POST /goals/suggest`). A free sentence becomes a goal (`POST /goals/draft`);
   the LLM may ask one question, and without an LLM a small parser asks for a missing amount. Goals carry
   `status` (suggested | confirmed), `origin` (data | ai | user) and a `note` saying why. Only confirmed goals are
   simulated in the overview and affect other goals.
2. **Main** (`pages/MainPage.tsx`, `mygoal/timeline.py`, `POST /timeline`): every confirmed goal on one chart. Spending
   goals take their money out at their date (a vertical drop), saving goals ("have X set aside", `kind: save`) and pension
   money are locked in their own colors; each goal's chance counts the goals before it as paid. Goals are edited or
   deleted right in the table. Actions are simply on or off and change the chart at once. The first goal failing in more
   than `app.planning.alert_failure` (10%) of futures is in focus (click another failing goal to switch): its actions list
   the engine's plan and the AI's ideas as **Recommended** (`POST /goals/{id}/ideas`, validated primitives, kept only if
   they help), each with the points it adds to that goal's chance, best first, plus "Activate all recommended" and
   "These actions raise your chances from X% to Y%" (green / yellow / red). "Move to 20xx" on a goal line adds a
   `move:<goal>:<date>` action (the June when 9 of 10 futures make it). Each what-if is a provisional card (accept or
   discard); the box is free again at once. Dates are years (goals are June 1). **Pro mode** is the full dashboard
   (fan chart with a worst-to-best future slider, levers, risk, advisor).
3. **Facts** ("See the data we're working with", `pages/FactsPage.tsx`, `mygoal/facts.py`): money in - out = free
   cash, life facts (known / assumed / you told us), assumptions about the future, every line editable (edits feed the
   engine: balances, income, housing and car costs, age and canton rebuild the profile); a chat at the
   bottom turns "my gross salary is 118k, we're expecting a baby" into edits and notes. Numbers only ever come from
   the data or the client; the LLM reads, phrases and maps (`POST /facts`, `/facts/edit`, `/facts/chat`, `GET /facts/ai`).

---

## The testdata: 8,000 people, and what a population adds

`config/app.yaml` -> `data.source: testdata` (the default now; `synthetic` brings Lena back). The organisers' relational
CSVs (people, accounts, 2.4M transactions, 2.3M events) are prepared once by `scripts/prep_testdata.py`; the app reads
only `data/testdata/*.parquet` (66 MB) via `mygoal/adapters/testdata.py` (mapping in `adapters/mappings/testdata.yaml`).
Dates are moved forward so the last data month is last month (`data.shift_to_today`), with a data note saying so.
The data has no goals: `config/goal_seeds.yaml` gives each client starting goals (home at the canton's median property
value from the data, travel for travel lovers, retirement). The UI picker searches all clients; starred ones come first.

What a population makes possible (numbers carry the source `population` = "Bank data: people like you"):

- **Data-calibrated risk** (`mygoal/population.py`, "population" service). One-off bills over CHF 1,000 (legal advice,
  vet, appliance and car repairs, moving) are measured per segment (age band x employment): about 1.2 a year, median
  CHF 2,300. The engine draws them as random shocks (compound Poisson, mean-preserving: the client's own big bills leave
  the variable-spending average), blended with the client's own year (the segment counts like two years of history).
  Spending noise is measured too. The risk card answers "when does it become critical": a bad year (1 in 10) vs the cash
  cushion, time to refill it, and how often cash dips below a month of spending. Employees show no salary gaps in the
  data, so job-loss risk stays at the Swiss default (said out loud in the card); self-employed "gaps" are payment rhythm.
- **Life-event evidence** (seasonally adjusted before/after per person, bootstrap CIs, n >= 20 or it isn't used):
  birth +CHF 790/month spending and ~CHF 2,800 around the birth (calibrates `have_child`), weddings a median CHF 36k
  (`wedding` lever), separations CHF 56k asset split and lawyers (`separation`), job changes +3% median but 46% took a
  cut (`job_change` draws one real outcome per future). The what-if agent has a `life_event_evidence` tool and cites
  how many people the numbers come from; keywords route "we're getting married" / "Trennung" to the levers.

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

**Options from other companies (the "manual API", `mygoal/partner_api/`).** The box "Options from other companies"
under the what-if box lists the client's connected integrations (connected before: `activated: true` in
`config/partners.yaml`), each with an "Ask for options" button and exactly what it receives: `{format, request,
language, customer_ref}`. For any other assistant it shows a fixed text to copy into that chat ("From your point of
view, with the information you have about the logged-in user, describe the options you recommend, in this format")
and a box for the JSON answer. The client is logged in there, so the text carries no client data. Answers
(`mygoal.scenarios/v1`: options built from the lever primitives, minus `goal_change`, `reallocate`, `loan`) become
actions with origin `partner`, every figure tagged source `partner`. Plan variants (`pick_one`) exclude each other,
invalid options come back with a correction text, and "What came back" shows the JSON as received. A new
integration is connected from its address: we check it publishes `{"format": "mygoal.scenarios/v1", "name",
"endpoint"}` there or at `/.well-known/mygoal-scenarios`, then call it with the `http` connector. Other transports:
`@connector("name")`. Demo: Alpenschutz (current insurer, connected) and Rigi (competitor, connect it with
`<app>/api/demo-partners/rigi`), both in `mock_insurer.py`. New building block `replace_spending`: a company gives only
the new price, and the bank fills in today's cost from the account (flagged "please check" when it sees none).

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
| GET | `/api/partner-prompt?lang=` | the text to copy into another company's chatbot (no client data) |
| POST | `/api/clients/{id}/scenarios/import` | `{goal_id, text, lang}`: the pasted answer -> new action ids, rejected, correction text, what came back |
| GET, POST, DELETE | `/api/clients/{id}/integrations[/{iid}]` | connected integrations with what each receives; connect from an address `{url}`; disconnect |
| POST | `/api/clients/{id}/integrations/{iid}/ask` | `{goal_id, lang}`: ask a connected API -> same result, plus what was sent |
| GET | `/api/scenario-format` | the format for companies building a compatible API |
| GET, POST | `/api/demo-partners/{pid}` | a demo company's description and its own API |
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

---

## Retaking the README screenshots

`scripts/take_screenshots.py` drives a running app with headless Chromium and writes `docs/screenshots/*.png`:

```bash
uv run --with playwright python scripts/take_screenshots.py --base http://127.0.0.1:8080 --client 0
```

- It first calls `POST /api/clients/{id}/reset`, which forgets the client's goals, dismissed suggestions, what-ifs, facts
  and integrations, so any number of runs start from the data. `--client` is an index in `/api/clients`.
- Each shot is cropped to the strip between two page elements (`shot()` in the script), so the images stay small. The
  flow: accept the AI's suggested goals, type two goals that are hard to reach, switch on options, ask a what-if, switch
  on its loan, ask a partner for options, open the advisor's view. The goals, the suggestions and the what-if use the LLM; without one the wording changes, and a goal
  sentence the rules parser cannot read makes the script stop.
- Use `127.0.0.1`: podman's port forward can reset `localhost` over IPv6.
- `--only 06,10` saves just those shots, but the script always replays the flow up to them.
