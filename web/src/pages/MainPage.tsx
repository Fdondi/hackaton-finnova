import { CalendarClock, CircleCheck, Database, FileText, Gauge, Handshake, House, LoaderCircle, Lock, Pencil, PiggyBank, Sparkles, Star, Target, Trash2, TreePalm, TriangleAlert, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { GoalSpec, LeverCard, Timeline, TimelineGoal } from '../api'
import { GoalEditor } from '../components/GoalEditor'
import { useTokens } from '../components/tokens'
import { ScenarioBox } from '../components/ScenarioBox'
import { WhatIfBox } from '../components/WhatIfBox'
import { Card, LeverIcon, Pill } from '../components/ui'
import { chf, chfCompact, monthLabel, onceAmount } from '../format'
import { useT } from '../i18n'

const pct = (x: number) => `${Math.round(x * 100)}%`
const ICON = { spend: Target, save: PiggyBank, retirement: TreePalm } as const
const ts = (iso: string) => Date.parse(iso)

interface Row { x: number; pension: number; locked: number; available: number; low: number; debt: number }

/** All goals on one timeline: spending goals take their money out, saving goals and pension money are locked.
 *  Only active actions are in it. Drops and locks are vertical: each goal date comes twice (before / after). */
function GoalsChart({ tl }: { tl: Timeline }) {
  const { t } = useT()
  const c = useTokens()
  const rows: Row[] = useMemo(() => tl.dates.map((d, i) => ({
    x: ts(d), pension: tl.pension[i], locked: tl.locked[i], available: Math.max(tl.free[i] - tl.locked[i], 0),
    low: Math.max(tl.free_low[i] - tl.locked[i], 0), debt: tl.debt?.[i] ?? 0,
  })), [tl])
  const first = new Date(tl.start).getFullYear(), last = new Date(tl.end).getFullYear()
  const step = Math.max(1, Math.ceil((last - first) / 9))
  const ticks = Array.from({ length: Math.floor((last - first) / step) + 1 }, (_, i) => Date.UTC(first + i * step, 0, 1))
  const risky = (g: TimelineGoal) => 1 - g.p > tl.alert_failure
  const violet = c['--series-violet'] || '#4a3aa7'
  const blue = c['--series-1'] || '#2a78d6'
  const debtColor = c['--series-2'] || '#eb6834'
  const inRange = tl.goals.filter((g) => g.date <= tl.end && g.type !== 'retirement')
  const events = (tl.events ?? []).filter((e) => e.date <= tl.end)
  const hasDebt = rows.some((r) => r.debt > 0)
  return (
    <div>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 34, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={c['--grid']} />
            <XAxis dataKey="x" type="number" scale="time" domain={['dataMin', 'dataMax']} ticks={ticks}
              tickFormatter={(x: number) => String(new Date(x).getUTCFullYear())} stroke={c['--axis']} tick={{ fill: c['--muted'], fontSize: 12 }} tickLine={false} />
            <YAxis tickFormatter={chfCompact} width={48} stroke={c['--axis']} tick={{ fill: c['--muted'], fontSize: 12 }} tickLine={false} axisLine={false} />
            <Tooltip cursor={{ stroke: c['--axis'] }} content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const r = payload[0].payload as Row
              return (
                <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                  <div className="mb-1 text-ink-2">{new Date(r.x).getUTCFullYear()}</div>
                  <div className="tabular">{t('flow.available', {}, 'Available')}: <b>{chf(r.available)}</b></div>
                  {r.locked > 0 && <div className="tabular">{t('flow.locked_goals', {}, 'Set aside for goals')}: <b>{chf(r.locked)}</b></div>}
                  <div className="tabular">{t('flow.pension_locked', {}, 'Pension (locked)')}: <b>{chf(r.pension)}</b></div>
                  <div className="tabular text-ink-2">{t('flow.bad_case', {}, 'Bad case (1 in 10)')}: {chf(r.low)}</div>
                  {r.debt > 0 && <div className="tabular">{t('flow.debt', {}, 'Debt')}: <b>{chf(r.debt)}</b></div>}
                </div>
              )
            }} />
            <Area dataKey="pension" stackId="w" type="linear" stroke="none" fill={c['--muted']} fillOpacity={0.25} isAnimationActive={false} />
            <Area dataKey="locked" stackId="w" type="linear" stroke="none" fill={violet} fillOpacity={0.45} isAnimationActive={false} />
            <Area dataKey="available" stackId="w" type="linear" stroke={c['--series-1']} strokeWidth={2} fill={c['--series-1']} fillOpacity={0.18} isAnimationActive={false} />
            <Line dataKey={(r: Row) => r.pension + r.locked + r.low} type="linear" stroke={c['--series-1']} strokeDasharray="3 4" strokeWidth={1} dot={false} isAnimationActive={false} />
            {hasDebt && <Line dataKey="debt" type="linear" stroke={debtColor} strokeWidth={2} dot={false} isAnimationActive={false} />}
            {inRange.map((g, i) => (
              <ReferenceLine key={g.id} x={ts(g.date)} stroke={risky(g) ? c['--critical'] : c['--good']} strokeWidth={risky(g) ? 2 : 1.5}
                strokeDasharray={risky(g) ? undefined : '4 3'}
                label={{ value: `${risky(g) ? '⚠ ' : ''}${g.label.length > 22 ? g.label.slice(0, 21) + '…' : g.label}`, position: 'top',
                  offset: i % 2 ? 4 : 18, fill: risky(g) ? c['--critical'] : c['--ink-2'], fontSize: 11, fontWeight: risky(g) ? 700 : 400 }} />
            ))}
            {events.map((e, i) => (
              <ReferenceLine key={`e-${e.date}-${e.label}`} x={ts(e.date)} stroke={e.kind === 'loan' ? debtColor : blue} strokeWidth={1.5}
                strokeDasharray={e.kind === 'loan' ? '2 2' : undefined}
                label={{ value: e.label.length > 22 ? e.label.slice(0, 21) + '…' : e.label, position: 'top',
                  offset: (inRange.length + i) % 2 ? 4 : 18, fill: e.kind === 'loan' ? debtColor : blue, fontSize: 11 }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-accent/30" />{t('flow.available', {}, 'Available')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm" style={{ background: violet, opacity: 0.55 }} />{t('flow.locked_goals', {}, 'Set aside for goals')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-muted/40" />{t('flow.pension_locked', {}, 'Pension (locked)')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-accent" />{t('flow.bad_case', {}, 'Bad case (1 in 10)')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-[var(--series-1)]" />{t('flow.purchase_event', {}, 'Purchase / investment')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t-2 border-[var(--series-2)]" />{t('flow.debt', {}, 'Debt')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-0.5 bg-[var(--series-2)]" />{t('flow.loan_event', {}, 'Loan')}</span>
        <span className="text-muted">{t('flow.active_only', {}, 'Includes the actions that are switched on.')}</span>
      </div>
    </div>
  )
}

/** One goal line: status, edit / delete in place, "move later", click to focus its actions. */
function GoalLine({ g, spec, tl, focused, onFocus, onSave, onDelete, onMoveLater }: {
  g: TimelineGoal; spec: GoalSpec | undefined; tl: Timeline; focused: boolean; onFocus: () => void
  onSave: (goal: GoalSpec) => void; onDelete: () => void; onMoveLater: () => void
}) {
  const { t, months } = useT()
  const [editing, setEditing] = useState(false)
  const Icon = g.type === 'home' ? House : ICON[g.kind]
  const bad = 1 - g.p > tl.alert_failure
  return (
    <li className={`py-2 ${focused ? 'bg-critical/5' : ''}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
        <Icon size={16} className="text-ink-2" />
        <button onClick={g.at_risk ? onFocus : undefined} className={`font-medium ${g.at_risk ? 'hover:underline' : 'cursor-default'}`}>{g.label}</button>
        <span className="text-ink-2">{g.type === 'retirement' ? t('flow.at_age', { age: g.retirement_age ?? '' }, `at ${g.retirement_age}`) : monthLabel(g.date, months())}</span>
        {g.moved && <Pill tone="accent"><CalendarClock size={11} />{t('flow.moved', {}, 'moved')}</Pill>}
        {g.amount !== null && g.type !== 'retirement' && <span className="text-ink-2 tabular">{chf(g.amount)}</span>}
        {g.kind === 'save' && <Pill tone="neutral"><Lock size={11} />{t('flow.kept_saved', {}, 'kept saved')}</Pill>}
        <span className={`ml-auto inline-flex items-center gap-1 font-medium ${bad ? 'text-critical' : 'text-good-text'}`}>
          {bad ? <TriangleAlert size={14} /> : <CircleCheck size={14} />}
          {t('flow.chance', { pct: pct(g.p) }, `${pct(g.p)} likely`)}
          {bad && g.shortfall ? <span className="font-normal">· {t('flow.shortfall_short', { amount: chf(g.shortfall) }, `shortfall ~${chf(g.shortfall)}`)}</span> : null}
        </span>
        {g.move_to && (
          <button onClick={onMoveLater} className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-0.5 text-xs font-medium hover:bg-surface-2"
            title={t('flow.move_hint', {}, '9 of 10 futures make it by then')}>
            <CalendarClock size={12} />{t('flow.move_later', { when: g.type === 'retirement' ? g.move_to.retirement_age ?? '' : g.move_to.date.slice(0, 4) }, `Move to ${g.move_to.date.slice(0, 4)}`)}
          </button>
        )}
        {spec && <button onClick={() => setEditing(!editing)} className="rounded p-1 text-ink-2 hover:bg-surface-2" aria-label={t('flow.edit', {}, 'Edit')} title={t('flow.edit', {}, 'Edit')}><Pencil size={13} /></button>}
        <button onClick={onDelete} className="rounded p-1 text-muted hover:text-critical" aria-label={t('flow.delete', {}, 'Delete')} title={t('flow.delete', {}, 'Delete')}><X size={14} /></button>
      </div>
      {editing && spec && <GoalEditor goal={spec} onCancel={() => setEditing(false)} onSave={(goal) => { setEditing(false); onSave(goal) }} />}
    </li>
  )
}

function dollars(gain: number, max: number) {
  if (!(max > 0) || !(gain > 0)) return gain < -0.005 ? '−' : ''
  const r = gain / max
  return r > 0.7 ? '💵💵💵' : r > 0.3 ? '💵💵' : '💵'
}

function ActionRow({ lv, on, recommended, gain, maxGain, onToggle, onDetails, onDelete }: {
  lv: LeverCard; on: boolean; recommended: boolean; gain: number | undefined; maxGain: number
  onToggle: (on: boolean) => void; onDetails: () => void; onDelete: () => void
}) {
  const { t } = useT()
  const agree = Boolean((lv.details as { needs_agreement?: boolean }).needs_agreement)
  const style = on ? 'border-accent bg-accent-wash' : recommended ? 'border-good/60 bg-good/10' : agree ? 'border-warning/70 bg-warning/10' : 'border-line bg-surface'
  return (
    <li className={`flex items-start gap-3 rounded-xl border p-2.5 transition ${style}`}>
      <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} className="mt-1.5 h-4 w-4 accent-[var(--series-1)]" aria-label={lv.title} />
      <LeverIcon name={lv.icon} origin={lv.origin === 'user' ? 'builtin' : lv.origin} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium leading-snug">{lv.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {recommended && <Pill tone="good"><Star size={11} />{t('flow.recommended', {}, 'Recommended')}</Pill>}
          {agree && <Pill tone="warning" title={lv.description}><TriangleAlert size={11} />{t('flow.needs_agreement', {}, 'Needs your agreement')}</Pill>}
          {lv.origin === 'agent' && <Pill tone="llm"><Sparkles size={11} />{t('flow.ai_idea', {}, 'AI idea')}</Pill>}
          {lv.origin === 'partner' && <Pill tone="warning" title={t('partners.from_hint', {}, 'Figures from another company: please check')}><Handshake size={11} />{String(lv.details.partner ?? '')}</Pill>}
          {lv.monthly_equivalent !== 0 && <span className="text-xs text-ink-2 tabular">{lv.monthly_equivalent > 0 ? '+' : ''}{chf(lv.monthly_equivalent)}/{t('ui.month_short', {}, 'mo')}</span>}
          {onceAmount(lv.details) !== 0 && <span className="text-xs text-ink-2 tabular">{chf(onceAmount(lv.details))} {t('flow.once_short', {}, 'once')}</span>}
          {lv.effort && <Pill>{t(`effort.${lv.effort}`)}</Pill>}
          {(lv.assumptions.length > 0 || Boolean((lv.details as { breakdown?: unknown }).breakdown)) && (
            <button onClick={onDetails} className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><FileText size={12} />{t('flow.details', {}, 'Details')}</button>
          )}
        </div>
      </div>
      {gain !== undefined && (
        <span className={`shrink-0 self-center rounded-lg px-2 py-1 text-sm font-semibold tabular ${gain > 0.005 ? 'bg-good/15 text-good-text' : gain < -0.005 ? 'bg-critical/10 text-critical' : 'bg-surface-2 text-ink-2'}`}
          title={t('flow.gain_hint', {}, 'How much this helps this goal, compared with the other actions. Never changes when you switch actions on or off.')}>
          {dollars(gain, maxGain) || '·'}
        </span>
      )}
      <button onClick={onDelete} className="rounded p-1 text-muted hover:text-critical" aria-label={t('flow.delete', {}, 'Delete')} title={t('flow.delete', {}, 'Delete')}><Trash2 size={14} /></button>
    </li>
  )
}

/** Actions for the goal in focus: each with a 💵 impact mark (scaled to the strongest action, frozen so it never moves). */
function ActionsCard({ tl, clientId, active, listed, ideasLoading, onToggle, onActivateAll, onDelete, onDetails, onLever, onScenarios, onMoreIdeas }: {
  tl: Timeline; clientId: string; active: string[]; listed: string[]; ideasLoading: boolean
  onToggle: (id: string, on: boolean) => void; onActivateAll: (ids: string[]) => void; onDelete: (id: string) => void
  onDetails: (id: string) => void; onLever: (id: string) => void; onScenarios: (ids: string[]) => void; onMoreIdeas: () => void
}) {
  const { t, months } = useT()
  const a = tl.actions!
  const frozen = useRef<Record<string, number>>({})
  const goalRef = useRef(a.goal_id)
  if (goalRef.current !== a.goal_id) {
    frozen.current = {}
    goalRef.current = a.goal_id
  }
  for (const [k, v] of Object.entries(a.gains)) {
    if (!(k in frozen.current)) frozen.current[k] = v
  }
  const ids = [...new Set([...a.recommended, ...listed, ...active])].filter((i) => tl.cards[i])
  const gain = (i: string) => frozen.current[i] ?? a.gains[i] ?? -1
  ids.sort((x, y) => gain(y) - gain(x))
  const maxGain = Math.max(0, ...ids.map((i) => gain(i)))
  const open = a.recommended.filter((i) => !active.includes(i))
  const tone = a.p_to >= 1 - tl.alert_failure ? 'bg-good/15 text-good-text' : a.p_to >= tl.success_threshold ? 'bg-warning/20 text-ink' : 'bg-critical/10 text-critical'
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">{t('flow.actions_for', { goal: a.goal_label, year: monthLabel(a.goal_date, months()) }, `What would help: ${a.goal_label}`)}</h2>
        {open.length > 0 && (
          <button onClick={() => onActivateAll(open)} className="inline-flex items-center gap-1 rounded-lg bg-good px-3 py-1.5 text-sm font-medium text-white">
            <Star size={14} />{t('flow.activate_all', {}, 'Activate all recommended')}
          </button>
        )}
      </div>
      <ul className="mt-3 space-y-2">
        {ids.map((i) => (
          <ActionRow key={i} lv={tl.cards[i]} on={active.includes(i)} recommended={a.recommended.includes(i)} gain={frozen.current[i] ?? a.gains[i]}
            maxGain={maxGain} onToggle={(on) => onToggle(i, on)} onDetails={() => onDetails(i)} onDelete={() => onDelete(i)} />
        ))}
        {ideasLoading && (
          <li className="flex items-center gap-2 rounded-xl border border-dashed border-llm/40 p-2.5 text-sm text-llm">
            <LoaderCircle size={14} className="animate-spin" />{t('flow.ai_thinking', {}, 'The AI is looking for ideas that fit you…')}
          </li>
        )}
      </ul>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button type="button" onClick={onMoreIdeas} disabled={ideasLoading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-llm/50 px-3 py-1.5 text-sm text-llm hover:bg-llm-wash disabled:opacity-50">
          {ideasLoading ? <LoaderCircle size={14} className="animate-spin" /> : <Sparkles size={14} />}
          {t('flow.more_ideas', {}, 'Ask for more ideas to save')}
        </button>
      </div>
      <div className="mt-3"><WhatIfBox clientId={clientId} goalId={a.goal_id} onLever={onLever} /></div>
      <div className="mt-3"><ScenarioBox clientId={clientId} goalId={a.goal_id} onScenarios={onScenarios} /></div>
      <div className={`mt-3 rounded-lg px-3 py-2 text-sm font-medium ${tone}`}>
        {Math.abs(a.p_to - a.p_from) < 0.005
          ? t('flow.chances_now', { pct: pct(a.p_to) }, `Chance today: ${pct(a.p_to)}. Switch on actions to raise it.`)
          : t('flow.chances_raise', { from: pct(a.p_from), to: pct(a.p_to) }, `These actions raise your chances from ${pct(a.p_from)} to ${pct(a.p_to)}.`)}
      </div>
    </Card>
  )
}

/** Page 2: every goal on one timeline, and the actions for the first goal that fails. */
export function MainPage({ clientId, tl, goals, active, listed, loading, ideasLoading, onToggle, onActivateAll, onDelete, onDetails, onLever,
  onScenarios, onFocus, onSaveGoal, onDeleteGoal, onPro, onFacts, onGoals, onMoreIdeas }: {
  clientId: string; tl: Timeline; goals: GoalSpec[]; active: string[]; listed: string[]; loading: boolean; ideasLoading: Record<string, boolean>
  onToggle: (id: string, on: boolean) => void; onActivateAll: (ids: string[]) => void; onDelete: (id: string) => void
  onDetails: (id: string) => void; onLever: (id: string) => void; onScenarios: (ids: string[]) => void; onFocus: (goalId: string) => void
  onSaveGoal: (g: GoalSpec) => void; onDeleteGoal: (goalId: string) => void; onPro: () => void; onFacts: () => void; onGoals: () => void
  onMoreIdeas: () => void
}) {
  const { t } = useT()
  return (
    <div className={`mx-auto max-w-5xl space-y-4 px-4 py-6 transition-opacity ${loading ? 'opacity-60' : ''}`}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-xl font-semibold">{t('flow.your_goals', {}, 'Your goals over time')}</h2>
          <button onClick={onGoals} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-ink-2 hover:bg-surface-2"><Pencil size={14} />{t('flow.add_goals', {}, 'Add goals')}</button>
        </div>
        <div className="mt-3"><GoalsChart tl={tl} /></div>
        <ul className="mt-4 divide-y divide-line border-t border-line text-sm">
          {tl.goals.map((g) => (
            <GoalLine key={g.id} g={g} spec={goals.find((x) => x.id === g.id)} tl={tl} focused={tl.actions?.goal_id === g.id}
              onFocus={() => onFocus(g.id)} onSave={onSaveGoal} onDelete={() => onDeleteGoal(g.id)}
              onMoveLater={() => g.move_to && onLever(g.move_to.action)} />
          ))}
        </ul>
      </Card>

      {tl.actions && (
        <ActionsCard tl={tl} clientId={clientId} active={active} listed={listed} ideasLoading={!!ideasLoading[tl.actions.goal_id]}
          onToggle={onToggle} onActivateAll={onActivateAll} onDelete={onDelete} onDetails={onDetails} onLever={onLever} onScenarios={onScenarios}
          onMoreIdeas={onMoreIdeas} />
      )}

      <div className="flex justify-between pb-16">
        <button onClick={onFacts} className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"><Database size={14} />{t('flow.see_data', {}, "See the data we're working with")}</button>
      </div>
      <button onClick={onPro} className="fixed right-6 bottom-6 z-20 inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-medium shadow-lg hover:bg-surface-2">
        <Gauge size={16} />{t('flow.pro_mode', {}, 'Pro mode')}
      </button>
    </div>
  )
}
