import { RotateCcw, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Assumption, LeverCard, MonthlyBreakdown, Source } from '../api'
import { chf, formatValue } from '../format'
import { useT } from '../i18n'
import { SourceBadge } from './ui'

function AssumptionRow({ a, onChange }: { a: Assumption; onChange: (key: string, value: number | null) => void }) {
  const { t } = useT()
  const hasRange = a.low !== null && a.high !== null && a.high > a.low
  const step = a.step ?? (hasRange ? (a.high! - a.low!) / 50 : 1)
  // the control follows the hand at once; the recalculated value comes back from the server and re-syncs it
  const [v, setV] = useState(a.value)
  useEffect(() => { setV(a.value) }, [a.value])
  return (
    <li className="border-b border-line py-3 last:border-0">
      <div className="flex items-start justify-between gap-2">
        <div className="text-sm">{a.label}</div>
        <div className="text-sm font-semibold whitespace-nowrap tabular">{formatValue(v, a.unit)}</div>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <SourceBadge source={a.source} label={a.source_label} />
        {a.needs_confirmation && <span className="inline-flex items-center gap-1 text-xs text-llm"><TriangleAlert size={12} aria-hidden />{t('ui.please_confirm', {}, 'please confirm')}</span>}
        {a.source === 'user' && (
          <button onClick={() => onChange(a.key, null)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><RotateCcw size={12} />{t('ui.reset', {}, 'reset')}</button>
        )}
      </div>
      {a.note && <p className="mt-1 text-xs text-muted">{a.note}</p>}
      {a.editable && (
        hasRange ? (
          <div className="mt-2 flex items-center gap-2">
            <span className="w-16 text-right text-xs text-muted tabular">{formatValue(a.low!, a.unit)}</span>
            <input type="range" min={a.low!} max={a.high!} step={step} value={v} aria-label={a.label}
              className={`flex-1 ${a.source === 'llm_estimate' ? 'llm' : ''}`}
              onChange={(e) => { const x = Number(e.target.value); setV(x); onChange(a.key, x) }} />
            <span className="w-16 text-xs text-muted tabular">{formatValue(a.high!, a.unit)}</span>
          </div>
        ) : (
          <input type="number" value={v} step={a.step ?? 'any'} aria-label={a.label}
            className="mt-2 w-40 rounded-lg border border-line bg-surface px-2 py-1 text-sm tabular"
            onChange={(e) => setV(Number(e.target.value))}
            onBlur={() => { if (!Number.isNaN(v) && v !== a.value) onChange(a.key, v) }} />
        )
      )}
    </li>
  )
}

function Details({ lever }: { lever: LeverCard }) {
  const { t } = useT()
  const d = lever.details as Record<string, unknown>
  if (Array.isArray(d.table)) {
    const rows = d.table as { deductible: number; premium_year: number; expected_cost: number; worst_case: number }[]
    return (
      <div className="mt-4">
        <table className="w-full text-sm tabular">
          <thead className="text-left text-xs text-ink-2">
            <tr><th className="py-1">{t('ui.deductible', {}, 'Deductible')}</th><th className="py-1 text-right">{t('ui.premiums', {}, 'Premiums/yr')}</th><th className="py-1 text-right">{t('ui.expected', {}, 'Expected cost')}</th><th className="py-1 text-right">{t('ui.worst', {}, 'Worst year')}</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.deductible} className={`border-t border-line ${r.deductible === d.recommended ? 'font-semibold' : ''} ${r.deductible === d.current ? 'text-ink-2' : ''}`}>
                <td className="py-1">{r.deductible.toLocaleString('en-US').replace(/,/g, '’')}{r.deductible === d.current ? ` (${t('ui.today_short', {}, 'today')})` : ''}</td>
                <td className="py-1 text-right">{chf(r.premium_year)}</td>
                <td className="py-1 text-right">{chf(r.expected_cost)}</td>
                <td className="py-1 text-right">{chf(r.worst_case)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-2">{t('ui.break_even', { amount: chf(Number(d.break_even_costs)) }, 'Worth it as long as your yearly medical costs stay below about {amount}.')}</p>
        <p className="mt-1 text-xs text-muted">{String(d.quote_source ?? '')}</p>
      </div>
    )
  }
  if (d.options_yearly && typeof d.options_yearly === 'object') {
    return (
      <ul className="mt-4 space-y-1 text-sm">
        {Object.entries(d.options_yearly as Record<string, number>).map(([k, v]) => (
          <li key={k} className={`flex justify-between ${k === d.chosen ? 'font-semibold' : 'text-ink-2'}`}><span>{k}</span><span className="tabular">{chf(v)}/yr</span></li>
        ))}
      </ul>
    )
  }
  return null
}

function RateSources({ details }: { details: Record<string, unknown> }) {
  const { t } = useT()
  const rows = details.rate_sources as { title: string; text: string; source: Source }[] | undefined
  if (!rows?.length) return null
  return (
    <div className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-3">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t('flow.rate_from', {}, 'Where the suggested interest rate comes from')}</h3>
      <ul className="mt-2 space-y-2">
        {rows.map((row) => (
          <li key={row.title}>
            <div className="flex flex-wrap items-center gap-1.5 text-sm font-medium">
              {row.title}
              <SourceBadge source={row.source} label={t(`sources.${row.source}`, {}, row.source)} />
            </div>
            <p className="mt-0.5 text-xs text-ink-2">{row.text}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function MonthlyFigure({ b }: { b: MonthlyBreakdown }) {
  const { t } = useT()
  if (!b.lines.length && !b.notes.length) return null
  const monthly = b.lines.filter((line) => line.kind !== 'once')
  const once = b.lines.filter((line) => line.kind === 'once')
  return (
    <div className="mt-4 rounded-lg border border-line bg-surface-2/60 p-3">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t('flow.how_monthly', {}, 'How we get to the monthly figure')}</h3>
      <p className="mt-1 text-xs text-ink-2">{t('flow.monthly_is_income', {}, 'The monthly figure is the ongoing income or cost. A purchase is paid once, like a goal.')}</p>
      {monthly.length > 0 && (
        <ul className="mt-2 space-y-1 text-sm">
          {monthly.map((line, i) => (
            <li key={`${line.label}-${i}`} className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block leading-snug">{line.label}</span>
                {line.explain && <span className="block text-xs text-ink-2">{line.explain}</span>}
              </span>
              <span className="shrink-0 tabular">{line.monthly > 0 ? '+' : ''}{chf(line.monthly)}/{t('ui.month_short', {}, 'mo')}</span>
            </li>
          ))}
          <li className="flex justify-between border-t border-line pt-1 font-medium">
            <span>{t('flow.monthly_total', {}, 'Counted as')}</span>
            <span className="tabular">{b.total > 0 ? '+' : ''}{chf(b.total)}/{t('ui.month_short', {}, 'mo')}</span>
          </li>
        </ul>
      )}
      {once.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-line pt-2 text-sm">
          <li className="text-xs font-semibold tracking-wide text-muted uppercase">{t('flow.once_heading', {}, 'Paid once')}</li>
          {once.map((line, i) => (
            <li key={`once-${line.label}-${i}`} className="flex items-start justify-between gap-3">
              <span className="min-w-0">
                <span className="block leading-snug">{line.label}</span>
                {line.explain && <span className="block text-xs text-ink-2">{line.explain}</span>}
              </span>
              <span className="shrink-0 tabular">{chf(line.amount)}</span>
            </li>
          ))}
        </ul>
      )}
      {b.notes.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-ink-2">{b.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
    </div>
  )
}

export function WhyDrawer({ title, description, sideEffects, assumptions, lever, notes, onChange, onClose }: {
  title: string; description?: string; sideEffects?: string[]; assumptions: Assumption[]; lever?: LeverCard
  notes?: { level: string; message: string }[]; onChange: (key: string, value: number | null) => void; onClose: () => void
}) {
  const { t } = useT()
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside className="h-full w-full max-w-md overflow-y-auto bg-surface p-5 shadow-2xl" onClick={(e) => e.stopPropagation()} aria-label={title}>
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="text-xs font-semibold tracking-wide text-muted uppercase">{t('ui.why')}</div>
            <h2 className="text-lg font-semibold">{title}</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-surface-2" aria-label="Close"><X size={18} /></button>
        </div>
        {description && <p className="mt-2 text-sm text-ink-2">{description}</p>}
        {sideEffects && sideEffects.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-ink-2">{sideEffects.map((s) => <li key={s}>{s}</li>)}</ul>
        )}
        {lever && <RateSources details={lever.details} />}
        {lever && <Details lever={lever} />}
        {lever && typeof (lever.details as { breakdown?: MonthlyBreakdown }).breakdown === 'object' && (lever.details as { breakdown?: MonthlyBreakdown }).breakdown && (
          <MonthlyFigure b={(lever.details as { breakdown: MonthlyBreakdown }).breakdown} />
        )}
        <h3 className="mt-5 text-xs font-semibold tracking-wide text-muted uppercase">{t('ui.assumptions')}</h3>
        <ul>{assumptions.map((a) => <AssumptionRow key={a.key} a={a} onChange={onChange} />)}</ul>
        {notes && notes.length > 0 && (
          <>
            <h3 className="mt-5 text-xs font-semibold tracking-wide text-muted uppercase">{t('ui.data_notes')}</h3>
            <ul className="mt-2 space-y-1 text-xs text-ink-2">{notes.map((n) => <li key={n.message}>{n.level === 'warning' ? '⚠ ' : ''}{n.message}</li>)}</ul>
          </>
        )}
      </aside>
    </div>
  )
}
