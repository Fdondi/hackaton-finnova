import { CalendarPlus, Check, CircleCheck, Database, FileText, Gauge, House, LoaderCircle, Lock, Pencil, PiggyBank, Sparkles, Target, Trash2, TreePalm, TriangleAlert } from 'lucide-react'
import { useMemo } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { LeverCard, Timeline, TimelineGoal } from '../api'
import { useTokens } from '../components/tokens'
import { WhatIfBox } from '../components/WhatIfBox'
import { Card, LeverIcon, Pill } from '../components/ui'
import { chf, chfCompact, monthLabel } from '../format'
import { useT } from '../i18n'

const pct = (x: number) => `${Math.round(x * 100)}%`
const ICON = { spend: Target, save: PiggyBank, retirement: TreePalm } as const
const ts = (iso: string) => Date.parse(iso)

interface Row { x: number; pension: number; locked: number; available: number; low: number }

/** All goals on one timeline: spending goals take their money out, saving goals and pension money are locked.
 *  Only accepted actions are in it. Drops and locks are vertical: each goal date comes twice (before / after). */
function GoalsChart({ tl }: { tl: Timeline }) {
  const { t } = useT()
  const c = useTokens()
  const rows: Row[] = useMemo(() => tl.dates.map((d, i) => ({
    x: ts(d), pension: tl.pension[i], locked: tl.locked[i], available: Math.max(tl.free[i] - tl.locked[i], 0),
    low: Math.max(tl.free_low[i] - tl.locked[i], 0),
  })), [tl])
  const first = new Date(tl.start).getFullYear(), last = new Date(tl.end).getFullYear()
  const step = Math.max(1, Math.ceil((last - first) / 9))
  const ticks = Array.from({ length: Math.floor((last - first) / step) + 1 }, (_, i) => Date.UTC(first + i * step, 0, 1))
  const risky = (g: TimelineGoal) => 1 - g.p > tl.alert_failure
  const violet = c['--series-violet'] || '#4a3aa7'
  const inRange = tl.goals.filter((g) => g.date <= tl.end && g.type !== 'retirement')
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
                </div>
              )
            }} />
            <Area dataKey="pension" stackId="w" type="linear" stroke="none" fill={c['--muted']} fillOpacity={0.25} isAnimationActive={false} />
            <Area dataKey="locked" stackId="w" type="linear" stroke="none" fill={violet} fillOpacity={0.45} isAnimationActive={false} />
            <Area dataKey="available" stackId="w" type="linear" stroke={c['--series-1']} strokeWidth={2} fill={c['--series-1']} fillOpacity={0.18} isAnimationActive={false} />
            <Line dataKey={(r: Row) => r.pension + r.locked + r.low} type="linear" stroke={c['--series-1']} strokeDasharray="3 4" strokeWidth={1} dot={false} isAnimationActive={false} />
            {inRange.map((g, i) => (
              <ReferenceLine key={g.id} x={ts(g.date)} stroke={risky(g) ? c['--critical'] : c['--good']} strokeWidth={risky(g) ? 2 : 1.5}
                strokeDasharray={risky(g) ? undefined : '4 3'}
                label={{ value: `${risky(g) ? '⚠ ' : ''}${g.label.length > 22 ? g.label.slice(0, 21) + '…' : g.label}`, position: 'top',
                  offset: i % 2 ? 4 : 18, fill: risky(g) ? c['--critical'] : c['--ink-2'], fontSize: 11, fontWeight: risky(g) ? 700 : 400 }} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-accent/30" />{t('flow.available', {}, 'Available')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm" style={{ background: violet, opacity: 0.55 }} />{t('flow.locked_goals', {}, 'Set aside for goals')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-3 w-4 rounded-sm bg-muted/40" />{t('flow.pension_locked', {}, 'Pension (locked)')}</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-accent" />{t('flow.bad_case', {}, 'Bad case (1 in 10)')}</span>
        <span className="text-muted">{t('flow.accepted_only', {}, 'Includes only the actions you accepted.')}</span>
      </div>
    </div>
  )
}

type State = 'accepted' | 'selected' | 'off'

function ActionRow({ lv, state, onCheck, onDetails, onDelete }: {
  lv: LeverCard; state: State; onCheck: (on: boolean) => void; onDetails: () => void; onDelete: () => void
}) {
  const { t } = useT()
  const ai = lv.origin === 'agent'
  const style = state === 'accepted' ? 'border-accent bg-accent-wash' : state === 'selected' ? 'border-dashed border-accent bg-surface' : 'border-line bg-surface opacity-75'
  return (
    <li className={`flex items-start gap-3 rounded-xl border p-2.5 transition ${style}`}>
      <input type="checkbox" checked={state !== 'off'} onChange={(e) => onCheck(e.target.checked)} className="mt-1.5 h-4 w-4 accent-[var(--series-1)]" aria-label={lv.title} />
      <LeverIcon name={lv.icon} origin={lv.origin} />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium leading-snug">{lv.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {state === 'accepted' && <Pill tone="accent"><Check size={11} />{t('flow.accepted', {}, 'Accepted')}</Pill>}
          {ai && <Pill tone="llm"><Sparkles size={11} />{t('flow.ai_idea', {}, 'AI idea')}</Pill>}
          {lv.impact_label && <Pill tone={(lv.months_gained ?? 0) > 0 || lv.delta_p > 0.005 ? 'good' : 'neutral'}>{lv.impact_label}</Pill>}
          {lv.monthly_equivalent !== 0 && <span className="text-xs text-ink-2 tabular">{lv.monthly_equivalent > 0 ? '+' : ''}{chf(lv.monthly_equivalent)}/{t('ui.month_short', {}, 'mo')}</span>}
          <Pill>{t(`effort.${lv.effort}`)}</Pill>
          <button onClick={onDetails} className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><FileText size={12} />{t('flow.details', {}, 'Details')}</button>
        </div>
      </div>
      <button onClick={onDelete} className="rounded p-1 text-muted hover:text-critical" aria-label={t('flow.delete', {}, 'Delete')} title={t('flow.delete', {}, 'Delete')}><Trash2 size={14} /></button>
    </li>
  )
}

export interface GoalActions {
  shown: string[]                                 // every action listed for this goal, until deleted
  selected: string[]                              // picked but not accepted yet (previewed)
}

/** A goal that fails in more than 1 of 10 futures: the risk and shortfall, actions (accepted / selected / off),
 *  what accepting the selection would do, a what-if box, and "move the date". */
function RiskCard({ g, tl, clientId, active, actions, ideasLoading, onAccept, onUnaccept, onSelect, onDelete, onDetails, onLever, onMove }: {
  g: TimelineGoal; tl: Timeline; clientId: string; active: string[]; actions: GoalActions; ideasLoading: boolean
  onAccept: (ids: string[]) => void; onUnaccept: (id: string) => void; onSelect: (id: string, on: boolean) => void
  onDelete: (id: string) => void; onDetails: (id: string) => void; onLever: (id: string) => void; onMove: (g: TimelineGoal) => void
}) {
  const { t, months } = useT()
  const state = (i: string): State => (active.includes(i) ? 'accepted' : actions.selected.includes(i) ? 'selected' : 'off')
  const order: Record<State, number> = { accepted: 0, selected: 1, off: 2 }
  const ids = [...new Set([...actions.shown, ...active.filter((i) => tl.cards[i])])]
    .filter((i) => tl.cards[i]).sort((a, b) => order[state(a)] - order[state(b)])
  const when = g.type === 'retirement' ? t('flow.at_age', { age: g.retirement_age ?? '' }, `at ${g.retirement_age}`) : monthLabel(g.date, months())
  const moveLabel = g.move_to && (g.type === 'retirement' ? t('flow.at_age', { age: g.move_to.retirement_age ?? '' }, `at ${g.move_to.retirement_age}`) : monthLabel(g.move_to.date, months()))
  const okNow = 1 - g.p <= tl.alert_failure
  const pending = actions.selected.filter((i) => !active.includes(i))
  const short = (v: number | null) => (v ? ` ${t('flow.shortfall', { amount: chf(v), year: when }, `Expected shortfall by ${when}: ${chf(v)}.`)}` : '')
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 bg-critical/10 px-4 py-3 text-critical">
        <TriangleAlert size={20} className="mt-0.5 shrink-0" />
        <div>
          <div className="font-semibold">{g.label} · {when}</div>
          <div className="text-sm">{t('flow.fail_chance', { pct: pct(1 - g.p_base) }, `Without changes, a ${pct(1 - g.p_base)} chance you won't make it.`)}</div>
        </div>
      </div>
      <div className="space-y-3 p-4">
        <div className="text-sm font-medium">{t('flow.our_proposal', {}, 'What would help')}</div>
        <ul className="space-y-2">
          {ids.map((i) => (
            <ActionRow key={i} lv={tl.cards[i]} state={state(i)} onDetails={() => onDetails(i)} onDelete={() => onDelete(i)}
              onCheck={(on) => (state(i) === 'accepted' ? onUnaccept(i) : onSelect(i, on))} />
          ))}
          {ideasLoading && (
            <li className="flex items-center gap-2 rounded-xl border border-dashed border-llm/40 p-2.5 text-sm text-llm">
              <LoaderCircle size={14} className="animate-spin" />{t('flow.ai_thinking', {}, 'The AI is looking for ideas that fit you…')}
            </li>
          )}
        </ul>
        <div className={`rounded-lg px-3 py-2 text-sm ${okNow ? 'bg-good/10 text-good-text' : 'bg-critical/10 text-critical'}`}>
          <div className="flex items-center gap-2 font-medium">
            {okNow ? <CircleCheck size={16} /> : <TriangleAlert size={16} />}
            {t('flow.with_accepted', { pct: pct(1 - g.p) }, `With your accepted actions: ${pct(1 - g.p)} chance of missing it.`)}
          </div>
          {!okNow && g.shortfall ? <div className="pl-6">{short(g.shortfall)}</div> : null}
        </div>
        {pending.length > 0 && g.p_preview !== null && (
          <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-accent px-3 py-2 text-sm">
            <span>
              {t('flow.if_accept', { n: pending.length, pct: pct(1 - g.p_preview) }, `If you accept the ${pending.length} selected: ${pct(1 - g.p_preview)} chance of missing it.`)}
              {1 - g.p_preview > tl.alert_failure ? short(g.shortfall_preview) : ''}
            </span>
            <button onClick={() => onAccept(pending)} className="ml-auto inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 font-medium text-white">
              <Check size={14} />{t('flow.accept_selected', {}, 'Accept selected actions')}
            </button>
          </div>
        )}
        <WhatIfBox clientId={clientId} goalId={g.id} onLever={onLever} />
        {g.move_to && moveLabel && (
          <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3 text-sm">
            <CalendarPlus size={16} className="text-ink-2" />
            <span className="text-ink-2">{t('flow.or_move', { when: moveLabel }, `Or move the date: ${moveLabel} makes it in 9 of 10 futures.`)}</span>
            <button onClick={() => onMove(g)} className="rounded-lg border border-line px-2.5 py-1 font-medium hover:bg-surface-2">
              {t('flow.move_to', { when: moveLabel }, `Move to ${moveLabel}`)}
            </button>
          </div>
        )}
      </div>
    </Card>
  )
}

/** Page 2: every goal on one timeline, and for each goal at risk what would bring it back. */
export function MainPage({ clientId, tl, active, actions, loading, ideasLoading, onAccept, onUnaccept, onSelect, onDelete, onDetails, onLever, onMove, onPro, onFacts, onGoals }: {
  clientId: string; tl: Timeline; active: string[]; actions: Record<string, GoalActions>; loading: boolean; ideasLoading: Record<string, boolean>
  onAccept: (ids: string[]) => void; onUnaccept: (id: string) => void; onSelect: (goalId: string, id: string, on: boolean) => void
  onDelete: (goalId: string, id: string) => void; onDetails: (id: string) => void; onLever: (goalId: string, id: string) => void
  onMove: (g: TimelineGoal) => void; onPro: () => void; onFacts: () => void; onGoals: () => void
}) {
  const { t, months } = useT()
  const risky = tl.goals.filter((g) => g.at_risk)
  return (
    <div className={`mx-auto max-w-5xl space-y-4 px-4 py-6 transition-opacity ${loading ? 'opacity-60' : ''}`}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-xl font-semibold">{t('flow.your_goals', {}, 'Your goals over time')}</h2>
          <button onClick={onGoals} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-ink-2 hover:bg-surface-2"><Pencil size={14} />{t('flow.change_goals', {}, 'Change goals')}</button>
        </div>
        <div className="mt-3"><GoalsChart tl={tl} /></div>
        <ul className="mt-4 divide-y divide-line border-t border-line text-sm">
          {tl.goals.map((g) => {
            const Icon = g.type === 'home' ? House : ICON[g.kind]
            const bad = 1 - g.p > tl.alert_failure
            return (
              <li key={g.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <Icon size={16} className="text-ink-2" />
                <span className="font-medium">{g.label}</span>
                <span className="text-ink-2">{g.type === 'retirement' ? t('flow.at_age', { age: g.retirement_age ?? '' }, `at ${g.retirement_age}`) : monthLabel(g.date, months())}</span>
                {g.amount !== null && g.type !== 'retirement' && <span className="text-ink-2 tabular">{chf(g.amount)}</span>}
                {g.kind === 'save' && <Pill tone="neutral"><Lock size={11} />{t('flow.kept_saved', {}, 'kept saved')}</Pill>}
                <span className={`ml-auto inline-flex items-center gap-1 font-medium ${bad ? 'text-critical' : 'text-good-text'}`}>
                  {bad ? <TriangleAlert size={14} /> : <CircleCheck size={14} />}
                  {t('flow.chance', { pct: pct(g.p) }, `${pct(g.p)} likely`)}
                  {bad && g.shortfall ? <span className="font-normal">· {t('flow.shortfall_short', { amount: chf(g.shortfall) }, `shortfall ~${chf(g.shortfall)}`)}</span> : null}
                </span>
              </li>
            )
          })}
        </ul>
      </Card>

      {risky.map((g) => (
        <RiskCard key={g.id} g={g} tl={tl} clientId={clientId} active={active} actions={actions[g.id] ?? { shown: g.proposal, selected: [] }}
          ideasLoading={!!ideasLoading[g.id]} onAccept={onAccept} onUnaccept={onUnaccept}
          onSelect={(id, on) => onSelect(g.id, id, on)} onDelete={(id) => onDelete(g.id, id)} onDetails={onDetails}
          onLever={(id) => onLever(g.id, id)} onMove={onMove} />
      ))}

      <div className="flex justify-between pb-16">
        <button onClick={onFacts} className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"><Database size={14} />{t('flow.see_data', {}, "See the data we're working with")}</button>
      </div>
      <button onClick={onPro} className="fixed right-6 bottom-6 z-20 inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-medium shadow-lg hover:bg-surface-2">
        <Gauge size={16} />{t('flow.pro_mode', {}, 'Pro mode')}
      </button>
    </div>
  )
}
