import { ArrowRight, CalendarClock, CircleHelp, Pencil } from 'lucide-react'
import { useState } from 'react'
import type { CrossGoalEffect, GoalSpec, PlanResponse } from '../api'
import { chf, monthLabel, monthsBetween } from '../format'
import { useT } from '../i18n'
import { FanChart } from './FanChart'
import { Futures } from './Futures'
import { GoalEditor } from './GoalEditor'
import { Card, Pill } from './ui'

export function GoalCard({ plan, cross, crossLoading, anyActive, onEditGoal, onWhy }: {
  plan: PlanResponse; cross: CrossGoalEffect[]; crossLoading: boolean; anyActive: boolean
  onEditGoal: (g: GoalSpec) => void; onWhy: () => void
}) {
  const { t, months } = useT()
  const [editing, setEditing] = useState(false)
  const s = plan.scenario
  const b = plan.baseline
  const onTrack = s.p_success >= 0.7
  const p50 = s.achieved.p50
  const moved = anyActive && b.achieved.p50 && p50 ? monthsBetween(p50, b.achieved.p50) : 0
  const gap = anyActive ? plan.gap_scenario : plan.gap_baseline

  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm text-ink-2">{t('ui.your_goal')}</div>
          <h2 className="text-xl font-semibold">{plan.goal.label}</h2>
          <div className="text-sm text-muted">
            {plan.goal.type === 'home' && `${chf(Number(plan.goal.params.price))} · `}
            {plan.goal.type === 'target' && `${chf(Number(plan.goal.params.amount))} · `}
            {t('ui.target')} {monthLabel(s.target_date, months())}
          </div>
        </div>
        <button onClick={() => setEditing(!editing)} className="rounded-lg p-2 text-ink-2 hover:bg-surface-2" aria-label="Edit goal"><Pencil size={16} /></button>
      </div>
      {editing && <GoalEditor goal={plan.goal} onSave={(g) => { setEditing(false); onEditGoal(g) }} onCancel={() => setEditing(false)} />}

      <div className="mt-4 grid gap-4 md:grid-cols-[auto_1fr] md:items-center">
        <div>
          <div className="text-sm text-ink-2">{onTrack ? t('ui.on_track', {}, 'On track') : t('ui.likely', {}, 'Likely')}</div>
          <div className={`text-5xl font-semibold tracking-tight ${onTrack ? 'text-good-text' : ''}`}>
            {p50 ? monthLabel(p50, months()) : '–'}
          </div>
          {moved !== 0 && (
            <div className="mt-1 text-sm text-ink-2">
              <span className="line-through">{monthLabel(b.achieved.p50, months())}</span>{' '}
              <Pill tone={moved > 0 ? 'good' : 'bad'}>{moved > 0 ? `−${moved}` : `+${-moved}`} {t('ui.months', {}, 'months')}</Pill>
            </div>
          )}
        </div>
        <div className="space-y-2 md:border-l md:border-line md:pl-5">
          <Futures n={s.futures_of_10} label={plan.texts.futures} />
          <div className={`text-base font-medium ${gap && gap > 0 ? '' : 'text-good-text'}`}>{anyActive ? plan.texts.gap_scenario : plan.texts.gap}</div>
          <div className="flex items-center gap-2 text-sm text-ink-2"><CalendarClock size={16} aria-hidden />{plan.texts.deadline}</div>
          {plan.texts.range && <div className="text-xs text-muted">{plan.texts.range}</div>}
        </div>
      </div>

      {plan.drivers.length > 0 && (
        <ul className="mt-4 space-y-1 rounded-xl bg-surface-2 px-4 py-3 text-sm">
          {plan.drivers.slice(0, 2).map((d) => <li key={d} className="flex gap-2"><ArrowRight size={14} className="mt-0.5 shrink-0 text-muted" />{d}</li>)}
        </ul>
      )}

      <div className="mt-4">
        <FanChart scenario={s} baseline={b} showBaseline={anyActive} />
      </div>

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-line pt-3">
        <div className="text-sm font-medium">{t('ui.others')}</div>
        <button onClick={onWhy} className="inline-flex items-center gap-1 text-sm text-accent hover:underline"><CircleHelp size={14} />{t('ui.assumptions')}</button>
      </div>
      <ul className={`mt-2 space-y-1 text-sm text-ink-2 ${crossLoading ? 'opacity-50' : ''}`}>
        {cross.length === 0 && !crossLoading && <li className="text-muted">–</li>}
        {cross.map((x) => (
          <li key={`${x.source_goal_id}-${x.goal_id}`} className="flex gap-2">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${x.delta_months && x.delta_months > 0 ? 'bg-critical' : 'bg-grid'}`} />{x.text}
          </li>
        ))}
      </ul>
    </Card>
  )
}
