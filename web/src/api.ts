// Typed client for the FastAPI backend. Mirrors mygoal/service.py models.

export type Source = 'transactions' | 'client_data' | 'user' | 'market_default' | 'llm_estimate' | 'population'

export interface Assumption {
  key: string
  label: string
  value: number
  low: number | null
  high: number | null
  unit: string
  source: Source
  source_label: string
  editable: boolean
  needs_confirmation: boolean
  note: string | null
  step: number | null
}

export interface GoalSpec {
  id: string
  type: string
  label: string
  target_date: string | null
  params: Record<string, number | string | boolean>
  priority: number
  status?: 'suggested' | 'confirmed'
  origin?: 'data' | 'ai' | 'user'
  note?: string | null
  i18n?: Record<string, { label: string; note: string }>
}

export type DraftResult =
  | { status: 'question'; question: string }
  | { status: 'goal'; goal: GoalSpec }
  | { status: 'error'; message: string }

export interface TimelineGoal {
  id: string
  label: string
  type: string
  kind: 'spend' | 'save' | 'retirement'
  date: string
  amount: number | null
  retirement_age: number | null
  p_base: number
  p: number
  at_risk: boolean
  proposal: string[]
  p_proposal: number | null
  move_to: { date: string; retirement_age: number | null } | null
  shortfall: number | null
  p_preview: number | null
  shortfall_preview: number | null
}

/** All confirmed goals on one chart (mygoal/timeline.py). */
export interface Timeline {
  dates: string[]
  free: number[]
  free_low: number[]
  locked: number[]
  pension: number[]
  start: string
  end: string
  goals: TimelineGoal[]
  cards: Record<string, LeverCard>
  alert_failure: number
}

export interface Fact {
  id: string
  group: 'money' | 'life' | 'future' | 'notes'
  kind: 'known' | 'assumed' | 'yours'
  label: string
  display: string
  value: number | string | null
  unit: string
  source: Source | null
  source_label: string | null
  editable: boolean
  input: 'number' | 'text' | 'none'
  note: string | null
  low?: number | null
  high?: number | null
  step?: number | null
}

export interface Facts {
  money: Fact[]
  life: Fact[]
  future: Fact[]
  notes: Fact[]
  summary: { money_in: number; money_out: number; free_cash: number }
  as_of: string
  data_notes: { level: 'info' | 'warning'; message: string }[]
}

export interface FactsReading {
  summary: string | null
  observations: { text: string; basis?: string }[]
  available: boolean
}

export interface WorstCaseSegment {
  start: string
  end: string
  job_loss_months: number
  job_loss_start: string | null
  market_shortfall: number
  text: string
}

export interface FanChart {
  dates: string[]
  p_min: number[]
  p10: number[]
  p25: number[]
  p50: number[]
  p75: number[]
  p90: number[]
  p_max: number[]
  need: number[]
  have_label: string
  need_label: string
  worst_case: WorstCaseSegment[]
}

export interface GoalOutcome {
  goal_id: string
  target_date: string
  p_success: number
  futures_of_10: number
  achieved: { p10: string | null; p50: string | null; p90: string | null; never_share: number; horizon_end: string }
  months_late: number | null
  have_at_target: number
  need_at_target: number
  shortfall_at_target: number
  binding: string | null
  constraint_pass: Record<string, number>
  p_buffer_breach: number
  fan: FanChart | null
}

export interface LeverCard {
  lever_id: string
  title: string
  description: string
  group: string
  effort: 'none' | 'low' | 'medium' | 'high'
  confidence: 'structural' | 'behavioural' | 'estimated'
  side_effects: string[]
  product_trigger: string | null
  icon: string | null
  origin: string
  details: Record<string, unknown>
  assumptions: Assumption[]
  months_gained: number | null
  delta_p: number
  monthly_equivalent: number
  impact_label: string
  active: boolean
  in_plan: boolean
  helps: boolean
  trade_off: boolean
  rank: number | null
}

export interface Deadline {
  status: 'on_track' | 'ok' | 'not_enough'
  start_by: string | null
  months_of_slack: number | null
  p_with_plan: number | null
}

export interface CrossGoalEffect {
  source_goal_id: string
  goal_id: string
  label: string
  from_label: string
  to_label: string
  delta_months: number | null
  text: string
}

export interface PlanResponse {
  client_id: string
  goal: GoalSpec
  baseline: GoalOutcome
  scenario: GoalOutcome
  gap_baseline: number | null
  gap_scenario: number | null
  plan: string[]
  plan_p_success: number | null
  deadline: Deadline
  deadline_for: 'active' | 'plan'
  levers: LeverCard[]
  cross_goal: CrossGoalEffect[]
  drivers: string[]
  texts: Record<string, string>
  assumptions: Assumption[]
  timing_ms: Record<string, number>
}

export interface Overview {
  client: { id: string; name: string; age: number; canton: string; household: { adults: number; children_birth_years: number[] } }
  as_of: string
  stand: {
    income_monthly: number
    spending_monthly: number
    fcf_monthly: number
    savings_rate: number
    buffer_months: number
    trend: { liquid_12m_ago: number; liquid_now: number; change: number; direction: 'up' | 'flat' | 'down' }
    opaque_monthly: number
    opaque_share: number
    opaque_breakdown: Record<string, number>
    liquid: number
    invested: number
    p3a: number
    p2: number
    gross_income: number
  }
  texts: Record<string, string>
  spending: { category: string; label: string; monthly: number; fixed: number; variable: number; opaque: boolean }[]
  hints: { kind: string; label: string; monthly_cost: number; evidence: string[]; booking_ids: string[] }[]
  goals: (GoalSpec & { status_info: { p_success: number; futures_of_10: number; p50: string | null; target_date: string; headline: string } | null })[]
  goal_types: string[]
  data_quality: { level: 'info' | 'warning'; message: string }[]
  recurring: RecurringGroup[]
  risk: RiskView | null
}

/** Surprise bills and income risk measured on people like this client (population data). */
export interface RiskView {
  segment: string
  segment_label: string
  n_people: number
  bill_rate: number
  bill_threshold: number
  bill_p50: number | null
  bill_p90: number | null
  bad_year: number
  personal_bills: number
  causes: string[]
  cushion: number
  cushion_times: number | null
  p_breach: number | null
  job_prob: number
  job_source: Source
  texts: string[]
}

export interface RecurringGroup {
  key: string
  merchant: string
  category: string
  period_label: string
  amount: number
  monthly_equivalent: number
  count: number
  first_date: string
  last_date: string
  next_expected: string
  active: boolean
  tags: string[]
  counterparty: string | null
  booking_ids: string[]
}

export interface Booking {
  id: string
  date: string
  amount: number
  merchant: string
  category: string | null
  category_label: string | null
  tags: string[]
  text: string
}

export interface WhatIfQuestion {
  id: string
  text: string
  kind: 'number' | 'choice' | 'text'
  unit: string | null
  options: string[]
  min: number | null
  max: number | null
  default: number | string | null
}

export interface WhatIfResult {
  session_id: string
  status: 'question' | 'lever' | 'existing_lever' | 'unsupported' | 'error'
  agent: 'llm' | 'rules' | 'specialist' | 'none'
  message: string
  question: WhatIfQuestion | null
  lever_id: string | null
  steps: { kind: string; name: string; summary: string }[]
  evaluation: { months_gained: number | null; monthly_equivalent: number; delta_p: number } | null
}

export interface AdvisorAgenda {
  client: Record<string, number | string>
  goal: GoalSpec
  headline: string
  gap: string
  deadline: string
  plan: string
  drivers: string[]
  top_levers: { lever_id: string; title: string; impact: string; monthly: number; effort: string; trade_off: boolean; side_effects: string[] }[]
  open_questions: { topic: string; we_assumed: string; source: Source }[]
  product_triggers: { product: string; label: string; reason: string; impact: string; timing: string; volume: number | null; lever_id: string | null }[]
}

export type Overrides = Record<string, Record<string, number>>

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

export const api = {
  meta: () => call<{ llm: { available: boolean; provider: string | null; model: string | null } }>('/meta'),
  i18n: (lang: string) => call<Record<string, unknown>>(`/i18n/${lang}`),
  clients: () => call<{ id: string; name: string }[]>('/clients'),
  overview: (client: string, lang: string) => call<Overview>(`/clients/${client}/overview?lang=${lang}`),
  bookings: (client: string, lang: string) => call<Booking[]>(`/clients/${client}/bookings?lang=${lang}`),
  plan: (client: string, body: { goal_id: string; active: string[]; overrides: Overrides; lang: string; include_cross_goal: boolean }, signal?: AbortSignal) =>
    call<PlanResponse>(`/clients/${client}/plan`, { method: 'POST', body: JSON.stringify(body), signal }),
  crossGoal: (client: string, body: { goal_id: string; active: string[]; overrides: Overrides; lang: string }, signal?: AbortSignal) =>
    call<CrossGoalEffect[]>(`/clients/${client}/cross-goal`, { method: 'POST', body: JSON.stringify(body), signal }),
  whatif: (client: string, goal_id: string, text: string, lang: string) =>
    call<WhatIfResult>(`/clients/${client}/whatif`, { method: 'POST', body: JSON.stringify({ goal_id, text, lang }) }),
  answer: (session: string, answer: string) =>
    call<WhatIfResult>(`/whatif/${session}/answer`, { method: 'POST', body: JSON.stringify({ answer }) }),
  removeLever: (client: string, lever: string) => call<{ ok: boolean }>(`/clients/${client}/levers/${encodeURIComponent(lever)}`, { method: 'DELETE' }),
  upsertGoal: (client: string, goal: GoalSpec) =>
    call<GoalSpec[]>(`/clients/${client}/goals/${goal.id}`, { method: 'PUT', body: JSON.stringify(goal) }),
  advisor: (client: string, goal: string, lang: string) => call<AdvisorAgenda>(`/clients/${client}/advisor?goal_id=${goal}&lang=${lang}`),
  goals: (client: string, lang = 'en') => call<GoalSpec[]>(`/clients/${client}/goals?lang=${lang}`),
  deleteGoal: (client: string, goal: string) => call<GoalSpec[]>(`/clients/${client}/goals/${goal}`, { method: 'DELETE' }),
  suggestGoals: (client: string, lang: string) =>
    call<GoalSpec[]>(`/clients/${client}/goals/suggest`, { method: 'POST', body: JSON.stringify({ lang }) }),
  draftGoal: (client: string, body: { text: string; lang: string; question?: string; answer?: string }) =>
    call<DraftResult>(`/clients/${client}/goals/draft`, { method: 'POST', body: JSON.stringify(body) }),
  facts: (client: string, overrides: Overrides, lang: string) =>
    call<Facts>(`/clients/${client}/facts`, { method: 'POST', body: JSON.stringify({ overrides, lang }) }),
  editFact: (client: string, id: string, value: number | string | null, overrides: Overrides, lang: string) =>
    call<{ overrides: Overrides; facts: Facts }>(`/clients/${client}/facts/edit`, { method: 'POST', body: JSON.stringify({ id, value, overrides, lang }) }),
  factsChat: (client: string, message: string, overrides: Overrides, lang: string) =>
    call<{ reply: string; changed: string[]; overrides: Overrides; facts: Facts }>(`/clients/${client}/facts/chat`,
      { method: 'POST', body: JSON.stringify({ message, overrides, lang }) }),
  factsReading: (client: string, lang: string) => call<FactsReading>(`/clients/${client}/facts/ai?lang=${lang}`),
  timeline: (client: string, body: { active: string[]; overrides: Overrides; lang: string; preview?: Record<string, string[]>; listed?: string[] }, signal?: AbortSignal) =>
    call<Timeline>(`/clients/${client}/timeline`, { method: 'POST', body: JSON.stringify(body), signal }),
  goalIdeas: (client: string, goal: string, lang: string) =>
    call<{ ids: string[] }>(`/clients/${client}/goals/${goal}/ideas`, { method: 'POST', body: JSON.stringify({ lang }) }),
}
