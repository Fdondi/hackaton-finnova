import { ChartLine, ChevronDown, Table2, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { GoalOutcome } from '../api'
import { chf, chfCompact, monthLabel } from '../format'
import { useT } from '../i18n'

const VARS = ['--series-1', '--series-2', '--muted', '--grid', '--axis', '--ink', '--ink-2', '--surface', '--critical'] as const

/** Chart colors are CSS tokens; SVG attributes need resolved values, re-read when the color scheme flips. */
function useTokens() {
  const read = () => Object.fromEntries(VARS.map((v) => [v, getComputedStyle(document.documentElement).getPropertyValue(v).trim()]))
  const [tokens, setTokens] = useState<Record<string, string>>(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setTokens(read())
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return tokens
}

interface Row {
  d: string
  bandFull: [number, number]
  band80: [number, number]
  band50: [number, number]
  p50: number
  need: number
  base?: number
}

// Nested confidence bands around one series: one hue, opacity increasing toward the center (sequential, not categorical).
const BAND_OPACITY = { full: 0.08, p80: 0.16, p50: 0.28 } as const

export function FanChart({ scenario, baseline, showBaseline }: { scenario: GoalOutcome; baseline: GoalOutcome; showBaseline: boolean }) {
  const { t, months } = useT()
  const c = useTokens()
  const [table, setTable] = useState(false)
  const [worstOpen, setWorstOpen] = useState(false)
  const [hoverSeg, setHoverSeg] = useState<number | null>(null)
  const fan = scenario.fan
  const rows: Row[] = useMemo(() => {
    if (!fan) return []
    const base = new Map((baseline.fan?.dates ?? []).map((d, i) => [d, baseline.fan!.p50[i]]))
    return fan.dates.map((d, i) => ({
      d, bandFull: [fan.p_min[i], fan.p_max[i]], band80: [fan.p10[i], fan.p90[i]], band50: [fan.p25[i], fan.p75[i]],
      p50: fan.p50[i], need: fan.need[i], base: base.get(d),
    }))
  }, [fan, baseline.fan])
  if (!fan) return null
  const years = rows.filter((r, i) => i === 0 || r.d.slice(0, 4) !== rows[i - 1].d.slice(0, 4)).map((r) => r.d).slice(1)
  const step = Math.max(1, Math.ceil(years.length / 8))
  const ticks = years.filter((_, i) => i % step === 0)
  const target = scenario.target_date

  const legend = [
    { key: 'have', label: t('ui.have'), color: c['--series-1'], opacity: 0, kind: 'line' as const },
    { key: 'band50', label: t('ui.band50', {}, 'Central 50% of futures'), color: c['--series-1'], opacity: BAND_OPACITY.p50, kind: 'band' as const },
    { key: 'band80', label: t('ui.band80', {}, 'Central 80% of futures'), color: c['--series-1'], opacity: BAND_OPACITY.p80, kind: 'band' as const },
    { key: 'bandFull', label: t('ui.bandFull', {}, 'Full range of futures'), color: c['--series-1'], opacity: BAND_OPACITY.full, kind: 'band' as const },
    { key: 'need', label: t('ui.need'), color: c['--series-2'], opacity: 0, kind: 'line' as const },
    ...(showBaseline ? [{ key: 'base', label: t('ui.today'), color: c['--muted'], opacity: 0, kind: 'line' as const }] : []),
  ]

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
        {legend.map((l) => (
          <span key={l.key} className="inline-flex items-center gap-1.5">
            {l.kind === 'band'
              ? <span className="h-3 w-4 rounded-sm" style={{ background: l.color, opacity: l.opacity * 3 }} />
              : <span className="h-0.5 w-4 rounded" style={{ background: l.color }} />}
            {l.label}
          </span>
        ))}
        {fan.worst_case.length > 0 && (
          <button className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-surface-2 ${worstOpen ? 'bg-surface-2' : ''}`}
            onClick={() => { setWorstOpen(!worstOpen); setHoverSeg(null) }}>
            <TriangleAlert size={14} className="text-critical" />{t('ui.explain_worst', {}, 'What made it that bad?')}
            <ChevronDown size={14} className={worstOpen ? 'rotate-180' : ''} />
          </button>
        )}
        <button className="ml-auto inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-surface-2" onClick={() => setTable(!table)}>
          {table ? <ChartLine size={14} /> : <Table2 size={14} />} {table ? t('ui.chart', {}, 'Chart') : t('ui.table', {}, 'Table')}
        </button>
      </div>
      {worstOpen && (
        <ul className="mb-2 space-y-1.5 rounded-lg border border-critical/30 bg-critical/5 p-2.5 text-xs">
          {fan.worst_case.map((seg, i) => (
            <li key={i} onMouseEnter={() => setHoverSeg(i)} onMouseLeave={() => setHoverSeg(null)}
              className={`cursor-default rounded-md px-1.5 py-1 transition-colors ${hoverSeg === i ? 'bg-critical/15' : ''}`}>
              <div className="text-ink-2">{t('ui.worst_case_valid_for', { start: monthLabel(seg.start, months()), end: monthLabel(seg.end, months()) },
                `This explanation covers ${monthLabel(seg.start, months())} – ${monthLabel(seg.end, months())}`)}</div>
              <div className="font-medium text-ink">{seg.text}</div>
            </li>
          ))}
        </ul>
      )}
      {table ? (
        <div className="max-h-72 overflow-auto rounded-lg border border-line">
          <table className="w-full text-sm tabular">
            <thead className="sticky top-0 bg-surface-2 text-left text-xs text-ink-2">
              <tr>
                <th className="px-3 py-1.5">{t('ui.date', {}, 'Date')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.have')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.band50', {}, 'Central 50% of futures')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.band80', {}, 'Central 80% of futures')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.bandFull', {}, 'Full range of futures')}</th>
                <th className="px-3 py-1.5 text-right">{t('ui.need')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.filter((r, i) => i === 0 || r.d.slice(0, 4) !== rows[i - 1].d.slice(0, 4) || r.d === target).map((r) => (
                <tr key={r.d} className={`border-t border-line ${r.d === target ? 'font-semibold' : ''}`}>
                  <td className="px-3 py-1">{monthLabel(r.d, months())}</td>
                  <td className="px-3 py-1 text-right">{chf(r.p50)}</td>
                  <td className="px-3 py-1 text-right text-ink-2">{chf(r.band50[0])} – {chf(r.band50[1])}</td>
                  <td className="px-3 py-1 text-right text-ink-2">{chf(r.band80[0])} – {chf(r.band80[1])}</td>
                  <td className="px-3 py-1 text-right text-ink-2">{chf(r.bandFull[0])} – {chf(r.bandFull[1])}</td>
                  <td className="px-3 py-1 text-right">{chf(r.need)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="h-72 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={rows} margin={{ top: 18, right: 12, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke={c['--grid']} />
              <XAxis dataKey="d" ticks={ticks} tickFormatter={(d: string) => d.slice(0, 4)} stroke={c['--axis']}
                tick={{ fill: c['--muted'], fontSize: 12 }} tickLine={false} />
              <YAxis tickFormatter={chfCompact} width={44} stroke={c['--axis']} tick={{ fill: c['--muted'], fontSize: 12 }}
                tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ stroke: c['--axis'], strokeWidth: 1 }}
                content={({ active, payload, label }) => {
                  if (!active || !payload?.length) return null
                  const r = payload[0].payload as Row
                  const line = (color: string, value: string, name: string) => (
                    <div className="flex items-center gap-2">
                      <span className="h-0.5 w-3 rounded" style={{ background: color }} />
                      <span className="font-semibold tabular">{value}</span>
                      <span className="text-ink-2">{name}</span>
                    </div>
                  )
                  return (
                    <div className="rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg">
                      <div className="mb-1 text-ink-2">{monthLabel(String(label), months())}</div>
                      {line(c['--series-1'], chf(r.p50), t('ui.have'))}
                      <div className="pl-5 text-ink-2 tabular">{t('ui.band50', {}, 'Central 50%')}: {chf(r.band50[0])} – {chf(r.band50[1])}</div>
                      <div className="pl-5 text-ink-2 tabular">{t('ui.band80', {}, 'Central 80%')}: {chf(r.band80[0])} – {chf(r.band80[1])}</div>
                      <div className="pl-5 text-ink-2 tabular">{t('ui.bandFull', {}, 'Full range')}: {chf(r.bandFull[0])} – {chf(r.bandFull[1])}</div>
                      {line(c['--series-2'], chf(r.need), t('ui.need'))}
                      {showBaseline && r.base !== undefined && line(c['--muted'], chf(r.base), t('ui.today'))}
                    </div>
                  )
                }}
              />
              {hoverSeg !== null && (
                <ReferenceArea x1={fan.worst_case[hoverSeg].start} x2={fan.worst_case[hoverSeg].end}
                  fill={c['--critical'] ?? '#d03b3b'} fillOpacity={0.12} stroke={c['--critical'] ?? '#d03b3b'} strokeOpacity={0.4} />
              )}
              <Area dataKey="bandFull" stroke="none" fill={c['--series-1']} fillOpacity={BAND_OPACITY.full} isAnimationActive={false} />
              <Area dataKey="band80" stroke="none" fill={c['--series-1']} fillOpacity={BAND_OPACITY.p80} isAnimationActive={false} />
              <Area dataKey="band50" stroke="none" fill={c['--series-1']} fillOpacity={BAND_OPACITY.p50} isAnimationActive={false} />
              {showBaseline && <Line dataKey="base" stroke={c['--muted']} strokeWidth={1.5} dot={false} isAnimationActive={false} />}
              <Line dataKey="need" stroke={c['--series-2']} strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="p50" stroke={c['--series-1']} strokeWidth={2} dot={false} isAnimationActive={false} />
              <ReferenceLine x={target} stroke={c['--ink-2']} strokeWidth={1}
                label={{ value: `${t('ui.target')} ${monthLabel(target, months())}`, position: 'top', fill: c['--ink-2'], fontSize: 12 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
