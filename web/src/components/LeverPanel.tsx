import { ChevronDown, CircleHelp, Star, Trash2, Wand2 } from 'lucide-react'
import { useState } from 'react'
import type { LeverCard, PlanResponse } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Button, Card, LeverIcon, Pill, Toggle } from './ui'

const GROUP_ORDER = ['no_lifestyle_cost', 'structural', 'behavioural', 'goal_change', 'agent']

function LeverRow({ lv, onToggle, onWhy, onRemove }: { lv: LeverCard; onToggle: (on: boolean) => void; onWhy: () => void; onRemove?: () => void }) {
  const { t } = useT()
  const gained = lv.months_gained ?? 0
  const tone = gained > 0 || lv.delta_p > 0.005 ? 'good' : gained < 0 ? 'bad' : 'neutral'
  const needsCheck = lv.assumptions.some((a) => a.source === 'llm_estimate' || a.needs_confirmation)
  return (
    <li className={`rounded-xl border p-3 transition ${lv.active ? 'border-accent bg-accent-wash' : 'border-line'}`}>
      <div className="flex items-start gap-3">
        <LeverIcon name={lv.icon} origin={lv.origin} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <div className="font-medium leading-snug">{lv.title}</div>
            <Toggle checked={lv.active} onChange={onToggle} label={lv.title} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {lv.impact_label && <Pill tone={tone}>{lv.impact_label}</Pill>}
            {lv.monthly_equivalent !== 0 && <span className="text-xs text-ink-2 tabular">{lv.monthly_equivalent > 0 ? '+' : ''}{chf(lv.monthly_equivalent)}/{t('ui.month_short', {}, 'mo')}</span>}
            <Pill>{t(`effort.${lv.effort}`)}</Pill>
            <Pill tone={lv.confidence === 'estimated' ? 'llm' : 'neutral'}>{t(`confidence.${lv.confidence}`)}</Pill>
            {lv.in_plan && <Pill tone="accent"><Star size={11} aria-hidden />{t('ui.in_plan')}</Pill>}
            {lv.trade_off && <Pill tone="bad">{t('ui.trade_off')}</Pill>}
          </div>
          {lv.side_effects[0] && <p className="mt-1.5 text-xs text-ink-2">{lv.side_effects[0]}</p>}
          <div className="mt-1 flex items-center gap-3">
            <button onClick={onWhy} className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
              <CircleHelp size={12} aria-hidden />{t('ui.why')}{needsCheck && <span className="text-llm">·  {t('ui.check_estimates', {}, 'check estimates')}</span>}
            </button>
            {onRemove && <button onClick={onRemove} className="inline-flex items-center gap-1 text-xs text-muted hover:text-critical"><Trash2 size={12} />{t('ui.remove', {}, 'Remove')}</button>}
          </div>
        </div>
      </div>
    </li>
  )
}

export function LeverPanel({ plan, onToggle, onUsePlan, onClear, onWhy, onRemove, children }: {
  plan: PlanResponse
  onToggle: (id: string, on: boolean) => void
  onUsePlan: () => void
  onClear: () => void
  onWhy: (id: string) => void
  onRemove: (id: string) => void
  children?: React.ReactNode
}) {
  const { t } = useT()
  const [showUnhelpful, setShowUnhelpful] = useState(false)
  const options = plan.levers.filter((l) => l.group !== 'life_event')
  const events = plan.levers.filter((l) => l.group === 'life_event')
  const helpful = options.filter((l) => l.helps || l.active)
  const unhelpful = options.filter((l) => !l.helps && !l.active)
  const groups = GROUP_ORDER.map((g) => ({
    g,
    items: helpful.filter((l) => (g === 'agent' ? l.origin === 'agent' : l.origin !== 'agent' && l.group === g)).sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99)),
  })).filter((x) => x.items.length)
  const row = (lv: LeverCard) => (
    <LeverRow key={lv.lever_id} lv={lv} onToggle={(on) => onToggle(lv.lever_id, on)} onWhy={() => onWhy(lv.lever_id)}
      onRemove={lv.origin === 'agent' ? () => onRemove(lv.lever_id) : undefined} />
  )

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{t('ui.options')}</h2>
        <div className="flex gap-1">
          <Button variant="primary" onClick={onUsePlan} disabled={!plan.plan.length}><Wand2 size={14} />{t('ui.suggested_plan')}</Button>
          <Button onClick={onClear}>{t('ui.clear')}</Button>
        </div>
      </div>
      {plan.texts.plan && <p className="mt-1 text-sm text-ink-2">{plan.texts.plan}</p>}
      {children}
      {groups.map(({ g, items }) => (
        <div key={g} className="mt-4">
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t(`groups.${g}`)}</h3>
          <ul className="space-y-2">{items.map(row)}</ul>
        </div>
      ))}
      {unhelpful.length > 0 && (
        <div className="mt-4">
          <button onClick={() => setShowUnhelpful(!showUnhelpful)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink-2">
            <ChevronDown size={14} className={showUnhelpful ? 'rotate-180' : ''} />{t('lever.no_effect')} ({unhelpful.length})
          </button>
          {showUnhelpful && <ul className="mt-2 space-y-2">{unhelpful.map(row)}</ul>}
        </div>
      )}
      {events.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">{t('ui.life_events')}</h3>
          <ul className="space-y-2">{events.map(row)}</ul>
        </div>
      )}
    </Card>
  )
}
