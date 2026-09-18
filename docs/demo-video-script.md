# Demo video script — My Goal, My Plan

Finnova hackathon, case 6. **75 seconds**, matching the whiteboard outline.
Product title in the header: **My Goal, My Plan**. Subtitle: **Will my money be enough for what matters to me?**

Speak at a calm 140 words/minute. Do not invent numbers in the take: read whatever the engine shows. A rehearsal sheet is at the end.

Recommended client: **Lena Brunner** (synthetic persona, `MYGOAL_DATA_SOURCE=synthetic`). Testdata works too (starred clients first in the picker) but the labels below are Lena’s.

---

## Run of show

| # | Beat | Screen | Time |
|---|---|---|---|
| 1 | Intro — background and objective | Title card, or header only | 0:00–0:10 |
| 2 | Goals — AI suggestions, accept / edit / add / delete, other profiles | Goals page | 0:10–0:20 |
| 3 | Action plan — current state, options, % contribution, what to do | Main page (`Your goals over time`) | 0:20–1:00 |
| 4 | Facts / assumptions | Facts page (`The data we're working with`) | 1:00–1:10 |
| 5 | End | Freeze on the raised chance, then title | 1:10–1:15 |

---

## Prep (before the camera)

1. English UI (header language toggle shows **DE**, so you are on EN).
2. LLM on (header bot chip shows the provider, not `AI off`).
3. Pick **Lena Brunner**. Stay on **Tell us your financial goal** until suggestions have loaded (desaturated ovals on the left, not the spinner `Finding ideas for you…`).
4. Browser zoom so the chart, goal list and `What would help` card all fit without scrolling.
5. One dry run: fill the rehearsal sheet. If a suggestion label differs, say the label on screen.

**Do not** open Pro mode, Advisor view, or the language toggle during the take.

---

## Shot list and voiceover

Live numbers are in `[brackets]`. Fill them from the rehearsal sheet.

### 1. Intro — 10 s

**Picture.** Header: *My Goal, My Plan* / *Will my money be enough for what matters to me?* Client picker on Lena. No talking-head needed.

**VO (~24 words).**

> Banks show you the past. We answer one question: will your money be enough for what matters to you? From your accounts — computed, not written by the AI.

---

### 2. Goals page — 10 s

**Picture.** `Hello Lena` · `Tell us your financial goal`. Left: `Suggestions for you` (grey dashed ovals, sparkle = AI). Right: `Your goals` (empty until you confirm). Footer disclaimer stays in frame.

This beat is too tight for one continuous click-through. **Jump-cut.**

| Cut | Time | Action | VO |
|---|---|---|---|
| A | 0:10–0:13 | Cursor on a grey suggestion. Click **✓ Confirm**. Chip turns colour and jumps to **Your goals**. | Suggestions come from *this* person’s data. Confirm what fits. |
| B | 0:13–0:16 | **Jump cut** to Marco & Sara (or Urs). Their suggestion list is different (house / family vs early retirement / hobby). | Switch the client: the ideas change. |
| C | 0:16–0:20 | Back on Lena. Click **✕** on one weak suggestion. Click **✎** on the home goal, change the year or price, **Save**. Type `I want a car in one year` in `I want to buy a car in one year…`, send. If the AI asks **One question**, answer in one word. Click **Show me my plan**. | Edit, drop, or write your own. Then see the plan. |

If the draft-goal LLM is slow, skip typing: confirm home + travel, delete one AI oval, click **Show me my plan**. The confirm / delete / continue already covers the outline.

**On-screen labels to hit:** `Suggestions for you` · `Your goals` · `Confirm` / `Edit` / `Delete` · `Show me my plan`.

---

### 3. Scenario / action plan — 40 s

**Picture.** Main page. Do not scroll away from: the chart, the goal table, and `What would help`.

#### 3a. Current state — 12 s (0:20–0:32)

**Action.** Hover the chart once so the tooltip shows `Available`, `Set aside for goals`, `Pension (locked)`, `Bad case (1 in 10)`. Point at the red goal line (⚠).

**VO.**

> Here is Lena now. Available cash in blue, money locked for goals, pension locked. Each goal is a date on the timeline. The one in red is at risk: **[home label]** in **[year]**, **[p]% likely**, shortfall about **[CHF]**.

#### 3b. Suggested options — 12 s (0:32–0:44)

**Action.** Pan to `What would help: [goal]`. Green **Recommended** stars, optional purple **AI idea**. Each row has **+N pts** on the right (change in that goal’s chance). Sort is already best-first.

Typical Lena rows, if they appear: `Put idle cash to work`, `Pay the maximum into pillar 3a`, car / deductible, subscriptions last. Say the titles on screen, not this list.

**VO.**

> For that goal, the engine ranks what would help. Each option shows how many points it adds to *this* chance — not a vibe, a simulation. Recommended first. Cancelling Netflix is not how you buy a home.

#### 3c. Contribution and what to do — 16 s (0:44–1:00)

**Action.**

1. Tick the top recommended checkbox. Chart and **[p]% likely** update. The green/yellow/red banner reads `These actions raise your chances from [from]% to [to]%`.
2. Tick a second option (or click **Activate all recommended**).
3. Optional, only if the banner already moved and you have ~6 s: type in `What if I…` → `What if I sell my Warhammer collection?` → **Try it**. If a card returns, **Accept this action**. If the AI is thinking, cut away — do not wait.

**VO.**

> Switch one on. The chart moves, and the chance moves with it. These actions raise her from **[from]%** to **[to]%**. That is the plan: do the high-point items, in this order.

---

### 4. Facts / assumptions — 10 s (1:00–1:10)

**Action.** Click **See the data we're working with** (bottom left of the main page).

**Picture, in this order (2–3 s each):**

1. `Financial facts`: **Money in / month − Money out / month = Free cash / month**.
2. `Life facts` legend: blue **we know** · purple **we assume** · green **you told us**. The card **What the AI reads in your data**.
3. `What we assume about the future`, with source chips (`From your account`, `Standard assumption`, `AI estimate, please check`). Optionally click **Edit** on one line and do not save — enough to show it is editable.

**VO.**

> Every number has a source: from the account, assumed, or she told us. The AI phrases this page. The engine still does the maths. She can change any line.

---

### 5. End — 5 s (1:10–1:15)

**Picture.** Cut back to the main page with the actions still on, banner `from [from]% to [to]%` in frame. Last frame: product title + subtitle.

**VO.**

> My Goal, My Plan. From the data the bank already has — to a plan she can act on.

---

## Teleprompter (VO only)

Banks show you the past. We answer one question: will your money be enough for what matters to you? From your accounts — computed, not written by the AI.

Suggestions come from this person’s data. Confirm what fits. Switch the client: the ideas change. Edit, drop, or write your own. Then see the plan.

Here is Lena now. Available cash in blue, money locked for goals, pension locked. Each goal is a date on the timeline. The one in red is at risk: *[read the goal line]*.

For that goal, the engine ranks what would help. Each option shows how many points it adds to this chance — not a vibe, a simulation. Recommended first. Cancelling Netflix is not how you buy a home.

Switch one on. The chart moves, and the chance moves with it. These actions raise her from *[from]* to *[to]*. That is the plan: do the high-point items, in this order.

Every number has a source: from the account, assumed, or she told us. The AI phrases this page. The engine still does the maths. She can change any line.

My Goal, My Plan. From the data the bank already has — to a plan she can act on.

---

## Rehearsal sheet (fill once, then film)

Do not copy README demo numbers into the take. They drift with the engine.

| What you will say | What the UI showed |
|---|---|
| Client | Lena Brunner / other: |
| Confirmed goals | |
| Failing goal label + year | |
| Chance today (`N% likely`) | |
| Shortfall | |
| Top 3 actions and their **pts** | |
| Banner from → to after toggles | |
| Money in / out / free cash | |

---

## If something is slow

| Problem | Cut |
|---|---|
| `Finding ideas for you…` still spinning | Wait off-camera, start the goals beat when ovals are there |
| Draft-goal / what-if LLM thinking | Skip typing; confirm + delete is enough |
| Main page `Loading…` | Hold on the previous frame; start 3a when the chart is drawn |
| No failing goal (all green) | Click a goal that is still below 100%, or pick another starred client |
| Testdata instead of Lena | Same script; say the name in the header and the labels on screen |

---

## Mapping to the product (for the editor)

| Whiteboard | Code |
|---|---|
| Intro | `ui.title` / `ui.subtitle` in the sticky header |
| Goals page | `web/src/pages/GoalsPage.tsx` — `POST /goals/suggest`, confirm / edit / delete chips, `POST /goals/draft`, `Show me my plan` |
| Different user profiles | Header client picker; AI suggestions keyed off `goal_assistant.situation` (age, family, shops, interests) |
| Scenario / action plan | `web/src/pages/MainPage.tsx` — timeline chart, `% likely`, `What would help`, **+N pts**, `Activate all recommended`, `These actions raise your chances from X% to Y%` |
| More details | `web/src/pages/FactsPage.tsx` — facts, source tags, known / assumed / yours, `POST /facts/chat` |
