import { CalendarClock, CircleHelp, Database, Gauge, ListChecks, Pencil } from 'lucide-react'
import { useMemo } from 'react'
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { CrossGoalEffect, LeverCard, PlanResponse } from '../api'
import { useTokens } from '../components/tokens'
import { Futures } from '../components/Futures'
import { WhatIfBox } from '../components/WhatIfBox'
import { Card, LeverIcon, Pill } from '../components/ui'
import { chf, chfCompact, delayLabel, monthLabel } from '../format'
import { useT } from '../i18n'

interface Row { d: string; base: number; plan?: number; need: number }

/** The sketch's "Scenario": today's path vs what the goal needs, and how much later it gets there (+3y). */
function ScenarioChart({ plan, withPlan }: { plan: PlanResponse; withPlan: boolean }) {
  const { t, months } = useT()
  const c = useTokens()
  const b = plan.baseline, s = plan.scenario
  const rows: Row[] = useMemo(() => {
    const bf = b.fan, sf = s.fan
    if (!bf) return []
    const planBy = new Map((sf?.dates ?? []).map((d, i) => [d, sf!.p50[i]]))
    const all = bf.dates.map((d, i) => ({ d, base: bf.p50[i], need: bf.need[i], plan: withPlan ? planBy.get(d) : undefined }))
    if (!withPlan || !sf?.dates.length) return all
    // end where the plan's line ends, but always show where today's path gets there
    const end = [sf.dates[sf.dates.length - 1], b.achieved.p50 ?? ''].sort().pop()!
    const cut = all.findIndex((r) => r.d > end)
    return cut < 0 ? all : all.slice(0, Math.min(all.length, cut + 2))
  }, [b.fan, s.fan, b.achieved.p50, withPlan])
  if (!rows.length) return null
  // the fan is sampled quarterly: put markers on the nearest sampled month
  const snap = (iso: string | null) => (iso ? rows.reduce((best, r) => (Math.abs(Date.parse(r.d) - Date.parse(iso)) < Math.abs(Date.parse(best) - Date.parse(iso)) ? r.d : best), rows[0].d) : null)
  const years = rows.filter((r, i) => i === 0 || r.d.slice(0, 4) !== rows[i - 1].d.slice(0, 4)).map((r) => r.d).slice(1)
  const ticks = years.filter((_, i) => i % Math.max(1, Math.ceil(years.length / 7)) === 0)
  const late = b.months_late ?? null
  const baseWhen = snap(b.achieved.p50)
  const planWhen = withPlan ? snap(s.achieved.p50) : null
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={c['--grid']} />
          <XAxis dataKey="d" ticks={ticks} tickFormatter={(d: string) => d.slice(0, 4)} stroke={c['--axis']}
            tick={{ fill: c['--muted'], fontSize: 12 }} tickLine={false} />
          <YAxis tickFormatter={chfCompact} width={44} stroke={c['--axis']} tick={{ fill: c['--muted'], fontSize: 12 }} tickLine={false} axisLine={false} />
          <Tooltip cursor={{ stroke: c['--axis'] }} content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null
            const r = payload[0].payload as Row
            return (
              <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                <div className="mb-1 text-ink-2">{monthLabel(String(label), months())}</div>
                <div className="tabular">{t('flow.today_path', {}, 'Today’s path')}: <b>{chf(r.base)}</b></div>
                {r.plan !== undefined && <div className="tabular">{t('flow.with_plan', {}, 'With your plan')}: <b>{chf(r.plan)}</b></div>}
                <div className="tabular">{t('ui.need')}: <b>{chf(r.need)}</b></div>
              </div>
            )
          }} />
          <Line dataKey="need" stroke={c['--series-2']} strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="base" stroke={withPlan ? c['--muted'] : c['--series-1']} strokeWidth={withPlan ? 1.5 : 2.5}
            strokeDasharray={withPlan ? '5 4' : undefined} dot={false} isAnimationActive={false} />
          {withPlan && <Line dataKey="plan" stroke={c['--series-1']} strokeWidth={2.5} dot={false} isAnimationActive={false} />}
          <ReferenceLine x={snap(s.target_date)!} stroke={c['--ink-2']}
            label={{ value: `${t('flow.your_date', {}, 'Your date')} ${monthLabel(s.target_date, months())}`, position: 'top', fill: c['--ink-2'], fontSize: 12 }} />
          {baseWhen && late !== null && late > 0 && (
            <ReferenceLine x={baseWhen} stroke={c['--critical']} strokeDasharray="4 3"
              label={{ value: delayLabel(late, t), position: 'insideTopRight', fill: c['--critical'], fontSize: 15, fontWeight: 700 }} />
          )}
          {planWhen && planWhen !== baseWhen && (
            <ReferenceLine x={planWhen} stroke={c['--good']} strokeDasharray="4 3" />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function Step({ n, lv, on, onToggle, onWhy }: { n: number; lv: LeverCard; on: boolean; onToggle: (on: boolean) => void; onWhy: () => void }) {
  const { t } = useT()
  const gained = lv.months_gained ?? 0
  return (
    <li className={`flex items-start gap-3 rounded-xl border p-3 transition ${on ? 'border-accent bg-accent-wash' : 'border-line'}`}>
      <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} className="mt-1.5 h-4 w-4 accent-[var(--series-1)]" aria-label={lv.title} />
      <span className="mt-0.5 w-5 text-sm font-semibold text-muted tabular">{n}.</span>
      <LeverIcon name={lv.icon} origin={lv.origin} />
      <div className="min-w-0 flex-1">
        <div className="font-medium leading-snug">{lv.title}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {lv.impact_label && <Pill tone={gained > 0 || lv.delta_p > 0.005 ? 'good' : 'neutral'}>{lv.impact_label}</Pill>}
          {lv.monthly_equivalent !== 0 && <span className="text-xs text-ink-2 tabular">{lv.monthly_equivalent > 0 ? '+' : ''}{chf(lv.monthly_equivalent)}/{t('ui.month_short', {}, 'mo')}</span>}
          <Pill>{t(`effort.${lv.effort}`)}</Pill>
          <button onClick={onWhy} className="inline-flex items-center gap-1 text-xs text-accent hover:underline"><CircleHelp size={12} />{t('ui.why')}</button>
        </div>
      </div>
    </li>
  )
}

/** Page 2: where the goal lands today, and the action plan that brings it back. Pro mode has everything else. */
export function MainPage({ clientId, plan, cross, active, loading, onToggle, onWhy, onLever, onPro, onFacts, onGoals }: {
  clientId: string; plan: PlanResponse; cross: CrossGoalEffect[]; active: string[]; loading: boolean
  onToggle: (id: string, on: boolean) => void; onWhy: (id: string) => void; onLever: (id: string) => void
  onPro: () => void; onFacts: () => void; onGoals: () => void
}) {
  const { t, months } = useT()
  const b = plan.baseline, s = plan.scenario
  const byId = new Map(plan.levers.map((l) => [l.lever_id, l]))
  const steps = plan.plan.map((id) => byId.get(id)).filter((l): l is LeverCard => !!l)
  const extra = active.map((id) => byId.get(id)).filter((l): l is LeverCard => !!l && !plan.plan.includes(l.lever_id))
  const withPlan = active.length > 0
  const late = b.months_late
  const onTrack = b.p_success >= 0.7

  return (
    <div className={`mx-auto max-w-5xl space-y-4 px-4 py-6 transition-opacity ${loading ? 'opacity-60' : ''}`}>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-sm text-ink-2">{t('flow.scenario', {}, 'Scenario')}</div>
            <h2 className="text-2xl font-semibold">{plan.goal.label}</h2>
            <div className="text-sm text-muted">
              {plan.goal.type === 'home' && `${chf(Number(plan.goal.params.price))} · `}
              {plan.goal.type === 'target' && `${chf(Number(plan.goal.params.amount))} · `}
              {t('ui.target')} {monthLabel(s.target_date, months())}
            </div>
          </div>
          <button onClick={onGoals} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-ink-2 hover:bg-surface-2"><Pencil size={14} />{t('flow.change_goals', {}, 'Change goals')}</button>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <div className="text-sm text-ink-2">{onTrack ? t('ui.on_track', {}, 'On track') : t('flow.today_likely', {}, 'As things are, likely')}</div>
            <div className="flex items-baseline gap-3">
              <span className="text-4xl font-semibold tracking-tight">{monthLabel(b.achieved.p50, months())}</span>
              {!onTrack && <span className="text-2xl font-bold text-critical">{delayLabel(late, t)}</span>}
            </div>
          </div>
          {withPlan && (
            <div>
              <div className="text-sm text-ink-2">{t('flow.with_plan', {}, 'With your plan')}</div>
              <div className="flex items-baseline gap-3">
                <span className="text-4xl font-semibold tracking-tight text-good-text">{monthLabel(s.achieved.p50, months())}</span>
                <span className="text-lg font-semibold text-ink-2">{delayLabel(s.months_late, t)}</span>
              </div>
            </div>
          )}
          <div className="min-w-[16rem] flex-1"><Futures n={s.futures_of_10} label={plan.texts.futures} /></div>
        </div>

        <div className="mt-4"><ScenarioChart plan={plan} withPlan={withPlan} /></div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
          <span className="inline-flex items-center gap-1.5"><span className={`h-0.5 w-4 ${withPlan ? 'border-t border-dashed border-muted' : 'bg-accent'}`} />{t('flow.today_path', {}, 'Today’s path')}</span>
          {withPlan && <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-accent" />{t('flow.with_plan', {}, 'With your plan')}</span>}
          <span className="inline-flex items-center gap-1.5"><span className="h-0.5 w-4 bg-need" />{t('ui.need')}</span>
          <span className="text-muted">{t('flow.median_note', {}, 'Middle of 1,000 simulated futures; Pro mode shows the whole range.')}</span>
        </div>
      </Card>

      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><ListChecks size={18} />{t('flow.action_plan', {}, 'Action plan')}</h2>
          {plan.plan_p_success !== null && (
            <span className="text-sm text-ink-2">{t('flow.plan_odds', { n: Math.round(plan.plan_p_success * 10) }, `All steps: ${Math.round(plan.plan_p_success * 10)} of 10 futures reach the goal`)}</span>
          )}
        </div>
        {steps.length === 0 ? (
          <p className="mt-3 text-sm text-ink-2">{onTrack ? t('flow.nothing_needed', {}, 'You are on track: nothing needs to change. Pro mode shows ways to get there even sooner.') : t('flow.no_plan', {}, 'No single change closes this gap. Pro mode shows every option, or change the goal.')}</p>
        ) : (
          <ol className="mt-3 space-y-2">
            {steps.map((lv, i) => <Step key={lv.lever_id} n={i + 1} lv={lv} on={active.includes(lv.lever_id)} onToggle={(on) => onToggle(lv.lever_id, on)} onWhy={() => onWhy(lv.lever_id)} />)}
            {extra.map((lv, i) => <Step key={lv.lever_id} n={steps.length + i + 1} lv={lv} on onToggle={(on) => onToggle(lv.lever_id, on)} onWhy={() => onWhy(lv.lever_id)} />)}
          </ol>
        )}
        <div className="mt-3 flex items-center gap-2 text-sm text-ink-2"><CalendarClock size={16} aria-hidden />{plan.texts.deadline}</div>
        {cross.length > 0 && (
          <ul className="mt-3 space-y-1 border-t border-line pt-3 text-sm text-ink-2">
            {cross.map((x) => <li key={`${x.source_goal_id}-${x.goal_id}`} className="flex gap-2"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${x.delta_months && x.delta_months > 0 ? 'bg-critical' : 'bg-grid'}`} />{x.text}</li>)}
          </ul>
        )}
        <div className="mt-4 border-t border-line pt-4">
          <WhatIfBox clientId={clientId} goalId={plan.goal.id} onLever={onLever} />
        </div>
      </Card>

      <div className="flex justify-between pb-16">
        <button onClick={onFacts} className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline"><Database size={14} />{t('flow.see_data', {}, "See the data we're working with")}</button>
      </div>
      <button onClick={onPro} className="fixed right-6 bottom-6 z-20 inline-flex items-center gap-2 rounded-xl border border-line bg-surface px-4 py-2.5 text-sm font-medium shadow-lg hover:bg-surface-2">
        <Gauge size={16} />{t('flow.pro_mode', {}, 'Pro mode')}
      </button>
    </div>
  )
}
