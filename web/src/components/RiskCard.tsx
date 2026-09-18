import { Umbrella } from 'lucide-react'
import type { Overview } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Card, SourceBadge } from './ui'

/** "When does it become critical?" Surprise bills measured on people like this client in the bank's data. */
export function RiskCard({ risk }: { risk: NonNullable<Overview['risk']> }) {
  const { t } = useT()
  const stats = [
    { label: t('ui.risk_rate', {}, 'Big bills a year'), value: risk.bill_rate.toFixed(1) },
    { label: t('ui.risk_bad_year', {}, 'Bad year (1 in 10)'), value: chf(risk.bad_year) },
    { label: t('ui.risk_cushion', {}, 'Your cash covers it'), value: risk.cushion_times != null ? `${risk.cushion_times.toFixed(1)}×` : '–' },
  ]
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Umbrella size={16} className="text-ink-2" aria-hidden />
        <h2 className="mr-auto font-semibold">{t('risk.title', {}, 'Surprise bills: people like you')}</h2>
        <SourceBadge source="population" label={t('sources.population', {}, 'Bank data: people like you')} />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg bg-surface-2 px-3 py-2">
            <div className="text-xs text-ink-2">{s.label}</div>
            <div className={`text-lg font-semibold tabular ${s.label === stats[2].label && (risk.cushion_times ?? 0) < 1 ? 'text-critical' : ''}`}>{s.value}</div>
          </div>
        ))}
      </div>
      <ul className="mt-3 space-y-1 text-sm text-ink-2">
        {risk.texts.map((x) => <li key={x}>{x}</li>)}
      </ul>
    </Card>
  )
}
