import { ArrowRight, Database, Search, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Booking, type Overview } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Card } from './ui'

const SERIES_VARS = ['--series-1', '--series-2', '--series-3', '--series-4', '--series-5', '--series-6', '--series-7', '--series-8'] as const

function useSeriesColors() {
  const read = () => SERIES_VARS.map((v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim())
  const [colors, setColors] = useState<string[]>(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setColors(read())
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return colors
}

interface Insight {
  id: string
  kind: 'hint' | 'recurring'
  label: string
  sub: string
  color: string
  bookingIds: string[]
}

/** Raw transactions on one side, extracted insights on the other, color-matched to the bookings behind them. */
export function DataInsightsView({ clientId, overview }: { clientId: string; overview: Overview | null }) {
  const { t, lang } = useT()
  const colors = useSeriesColors()
  const [bookings, setBookings] = useState<Booking[] | null>(null)
  const [filter, setFilter] = useState('')
  const [flashId, setFlashId] = useState<string | null>(null)
  const cursor = useRef<Record<string, number>>({})
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    setBookings(null)
    api.bookings(clientId, lang).then(setBookings)
  }, [clientId, lang])

  const insights = useMemo<Insight[]>(() => {
    if (!overview) return []
    const hints: Insight[] = overview.hints
      .filter((h) => h.booking_ids.length > 0)
      .map((h) => ({ id: `hint:${h.kind}`, kind: 'hint', label: h.label, sub: chf(h.monthly_cost) + '/mo', bookingIds: h.booking_ids, color: '' }))
    const recurring: Insight[] = overview.recurring
      .filter((r) => r.booking_ids.length > 0)
      .map((r) => ({ id: `recurring:${r.key}`, kind: 'recurring', label: r.merchant, sub: `${chf(r.monthly_equivalent)}/mo · ${r.period_label}`, bookingIds: r.booking_ids, color: '' }))
    const all = [...hints, ...recurring]
    return all.map((ins, i) => ({ ...ins, color: colors[i % colors.length] || '#888' }))
  }, [overview, colors])

  // First matching insight wins a row's color; a row can be evidence for more than one insight.
  const byBooking = useMemo(() => {
    const m = new Map<string, Insight>()
    for (const ins of insights) for (const id of ins.bookingIds) if (!m.has(id)) m.set(id, ins)
    return m
  }, [insights])

  const rows = useMemo(() => {
    if (!bookings) return []
    const q = filter.trim().toLowerCase()
    return q ? bookings.filter((b) => b.merchant.toLowerCase().includes(q) || b.text.toLowerCase().includes(q) || b.category_label?.toLowerCase().includes(q)) : bookings
  }, [bookings, filter])

  function seeSource(ins: Insight) {
    if (!ins.bookingIds.length) return
    const i = ((cursor.current[ins.id] ?? -1) + 1) % ins.bookingIds.length
    cursor.current[ins.id] = i
    const id = ins.bookingIds[i]
    setFilter('')
    requestAnimationFrame(() => {
      const el = document.getElementById(`booking-${id}`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setFlashId(id)
      if (flashTimer.current) clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setFlashId(null), 1600)
    })
  }

  if (!overview) return <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>

  return (
    <div className="grid gap-4 lg:grid-cols-12">
      <Card className="p-5 lg:col-span-7">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 text-lg font-semibold"><Database size={16} />{t('ui.raw_data', {}, 'Raw data')}</h2>
          <div className="relative">
            <Search size={14} className="absolute top-2.5 left-2.5 text-muted" aria-hidden />
            <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('ui.filter_transactions', {}, 'Filter…')}
              className="w-48 rounded-lg border border-line bg-surface py-1.5 pr-2 pl-8 text-sm placeholder:text-muted" />
          </div>
        </div>
        <div className="mt-3 max-h-[70vh] overflow-y-auto rounded-lg border border-line">
          <table className="w-full text-sm tabular">
            <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2">
              <tr>
                <th className="px-3 py-1.5">{t('ui.date', {}, 'Date')}</th>
                <th className="px-3 py-1.5">{t('ui.merchant', {}, 'Merchant')}</th>
                <th className="px-3 py-1.5">{t('ui.category', {}, 'Category')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.amount', {}, 'Amount')}</th>
              </tr>
            </thead>
            <tbody>
              {!bookings ? (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-ink-2">{t('ui.thinking', {}, 'Loading…')}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-ink-2">{t('ui.no_results', {}, 'No matching transactions')}</td></tr>
              ) : rows.map((b) => {
                const ins = byBooking.get(b.id)
                const flashing = flashId === b.id
                return (
                  <tr key={b.id} id={`booking-${b.id}`}
                    className={`border-t border-line transition-shadow ${flashing ? 'ring-inset ring-2 ring-ink' : ''}`}
                    style={ins ? { boxShadow: `inset 3px 0 0 0 ${ins.color}`, background: `color-mix(in srgb, ${ins.color} 8%, transparent)` } : undefined}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-ink-2">{b.date}</td>
                    <td className="px-3 py-1.5">{b.merchant}</td>
                    <td className="px-3 py-1.5 text-ink-2">{b.category_label ?? b.category ?? '–'}</td>
                    <td className={`px-3 py-1.5 text-right ${b.amount < 0 ? '' : 'text-good-text'}`}>{chf(b.amount)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-5 lg:col-span-5">
        <h2 className="flex items-center gap-2 text-lg font-semibold"><Sparkles size={16} className="text-llm" />{t('ui.insights', {}, 'Insights')}</h2>
        <p className="mt-1 text-sm text-ink-2">{t('ui.insights_sub', {}, 'What we extracted from the raw data on the left.')}</p>
        <ul className="mt-3 space-y-2">
          {insights.length === 0 && <li className="text-sm text-ink-2">{t('ui.no_insights', {}, 'No insights yet.')}</li>}
          {insights.map((ins) => (
            <li key={ins.id} className="rounded-xl border border-line p-3">
              <div className="flex items-start gap-2.5">
                <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ background: ins.color }} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="font-medium leading-snug">{ins.label}</div>
                  <div className="text-xs text-ink-2 tabular">{ins.sub} · {ins.bookingIds.length} {t('ui.transactions', {}, 'transactions')}</div>
                  <button onClick={() => seeSource(ins)} className="mt-1 inline-flex items-center gap-1 text-xs font-medium hover:underline" style={{ color: ins.color }}>
                    {t('ui.see_source', {}, 'See where this comes from')}<ArrowRight size={12} aria-hidden />
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
