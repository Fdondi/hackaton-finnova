import { ArrowDown, ArrowRight, ArrowUp, Eye, PiggyBank, ShieldCheck, Wallet } from 'lucide-react'
import type { Overview } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Card } from './ui'

/** "Where do I stand today?" in four tiles: label, value, one sentence. */
export function StandTiles({ ov }: { ov: Overview }) {
  const { t } = useT()
  const s = ov.stand
  const TrendIcon = s.trend.direction === 'up' ? ArrowUp : s.trend.direction === 'down' ? ArrowDown : ArrowRight
  const tiles = [
    { icon: Wallet, label: t('ui.fcf_label', {}, 'Left each month'), value: chf(s.fcf_monthly), sub: `${Math.round(s.savings_rate * 100)}% ${t('ui.of_income', {}, 'of income')}`, text: ov.texts.fcf },
    { icon: ShieldCheck, label: t('ui.buffer_label', {}, 'Safety cushion'), value: `${s.buffer_months.toFixed(0)} ${t('ui.months', {}, 'months')}`, sub: chf(s.liquid), text: ov.texts.buffer },
    { icon: PiggyBank, label: t('ui.trend_label', {}, 'Last 12 months'), value: `${s.trend.change >= 0 ? '+' : ''}${chf(s.trend.change)}`, sub: '', text: ov.texts.trend, trend: TrendIcon },
    { icon: Eye, label: t('ui.opaque_label', {}, "Can't see into"), value: chf(s.opaque_monthly), sub: `${Math.round(s.opaque_share * 100)}% ${t('ui.of_spending', {}, 'of spending')}`, text: ov.texts.opaque },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label} className="p-4">
          <div className="flex items-center gap-2 text-sm text-ink-2">
            <tile.icon size={16} aria-hidden />
            {tile.label}
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl font-semibold">{tile.value}</span>
            {tile.trend && <tile.trend size={18} className={s.trend.direction === 'down' ? 'text-critical' : 'text-good-text'} aria-hidden />}
            {tile.sub && <span className="text-sm text-muted">{tile.sub}</span>}
          </div>
          <p className="mt-1 text-xs text-ink-2">{tile.text}</p>
        </Card>
      ))}
    </div>
  )
}
