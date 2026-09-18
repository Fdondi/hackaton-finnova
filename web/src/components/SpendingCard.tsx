import { useEffect, useState } from 'react'
import type { Overview } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Card } from './ui'

/** Where the money goes: one series, so one color; values labelled at the bar end; opaque flows marked. */
export function SpendingCard({ ov }: { ov: Overview }) {
  const { t } = useT()
  const [color, setColor] = useState('#2a78d6')
  useEffect(() => { setColor(getComputedStyle(document.documentElement).getPropertyValue('--series-1').trim()) }, [])
  const rows = ov.spending.slice(0, 10)
  const max = Math.max(...rows.map((r) => r.monthly), 1)
  return (
    <Card className="p-5">
      <div className="flex items-baseline justify-between">
        <h2 className="font-semibold">{t('ui.money_goes', {}, 'Where your money goes')}</h2>
        <span className="text-sm text-ink-2 tabular">{chf(ov.stand.spending_monthly)}/{t('ui.month_short', {}, 'mo')}</span>
      </div>
      <ul className="mt-3 space-y-1.5">
        {rows.map((r) => (
          <li key={r.category} className="grid grid-cols-[9rem_1fr_5.5rem] items-center gap-2 text-sm" title={`${r.label}: ${chf(r.monthly)}`}>
            <span className="truncate text-ink-2">{r.label}</span>
            <span className="h-3">
              <span className="block h-3 rounded-r" style={{
                width: `${(100 * r.monthly) / max}%`,
                background: r.opaque ? `repeating-linear-gradient(45deg, ${color}, ${color} 3px, transparent 3px, transparent 6px)` : color,
                opacity: r.opaque ? 0.7 : 1,
              }} />
            </span>
            <span className="text-right tabular">{chf(r.monthly)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">{t('ui.opaque_hint', {}, 'Hatched: cash, TWINT and card bills we can’t see into.')}</p>
    </Card>
  )
}
