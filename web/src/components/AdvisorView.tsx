import { Briefcase, CalendarClock, CircleHelp, ListChecks, LoaderCircle } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type AdvisorAgenda } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Card, Pill, SourceBadge } from './ui'

/** Same engine, framed for the advisor: agenda, open questions, product triggers. Internal, not client advice. */
export function AdvisorView({ clientId, goalId }: { clientId: string; goalId: string }) {
  const { t, lang } = useT()
  const [agenda, setAgenda] = useState<AdvisorAgenda | null>(null)
  useEffect(() => {
    let live = true
    setAgenda(null)
    api.advisor(clientId, goalId, lang).then((a) => live && setAgenda(a))
    return () => { live = false }
  }, [clientId, goalId, lang])
  if (!agenda) return <div className="flex items-center gap-2 p-10 text-ink-2"><LoaderCircle className="animate-spin" size={18} />{t('ui.thinking')}</div>
  const c = agenda.client
  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-advisor p-5 text-white">
        <div className="flex items-center gap-2 text-xs tracking-wide text-white/60 uppercase"><Briefcase size={14} />{t('ui.advisor_internal', {}, 'Advisor view · internal')}</div>
        <div className="mt-1 text-2xl font-semibold">{String(c.name)}, {String(c.age)} · {String(c.canton)}</div>
        <div className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[['Gross income', chf(Number(c.gross_income))], ['Liquid', chf(Number(c.liquid))], ['Pillar 2', chf(Number(c.p2))], ['Saves / month', chf(Number(c.fcf_monthly))]].map(([k, v]) => (
            <div key={k}><div className="text-white/60">{k}</div><div className="text-lg font-semibold">{v}</div></div>
          ))}
        </div>
        <div className="mt-4 space-y-1 text-sm">
          <div className="font-medium">{agenda.headline}</div>
          <div className="text-white/80">{agenda.gap} · {agenda.deadline}</div>
          {agenda.drivers.map((d) => <div key={d} className="text-white/70">{d}</div>)}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <h3 className="flex items-center gap-2 font-semibold"><ListChecks size={16} />{t('ui.agenda', {}, 'Conversation agenda')}</h3>
          <ol className="mt-3 space-y-3">
            {agenda.top_levers.map((l, i) => (
              <li key={l.lever_id} className="flex gap-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-wash text-xs font-semibold text-accent">{i + 1}</span>
                <div>
                  <div className="font-medium">{l.title} {l.trade_off && <Pill tone="bad">{t('ui.trade_off')}</Pill>}</div>
                  <div className="text-sm text-ink-2">{l.impact}{l.monthly ? ` · ${chf(l.monthly)}/mo` : ''} · {t(`effort.${l.effort}`)}</div>
                  {l.side_effects[0] && <div className="text-xs text-muted">{l.side_effects[0]}</div>}
                </div>
              </li>
            ))}
          </ol>
          <h3 className="mt-6 flex items-center gap-2 font-semibold"><CircleHelp size={16} />{t('ui.open_questions', {}, 'Ask the client')}</h3>
          <ul className="mt-2 divide-y divide-line">
            {agenda.open_questions.map((q) => (
              <li key={q.topic + q.we_assumed} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <span>{q.topic}</span>
                <span className="flex items-center gap-2 text-ink-2"><span className="tabular">{q.we_assumed}</span><SourceBadge source={q.source} label={t(`sources.${q.source}`)} /></span>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="p-5">
          <h3 className="flex items-center gap-2 font-semibold"><CalendarClock size={16} />{t('ui.triggers', {}, 'Product triggers')}</h3>
          <ul className="mt-3 space-y-3">
            {agenda.product_triggers.map((p) => (
              <li key={p.product + p.reason} className="rounded-xl border border-line p-3">
                <div className="flex items-center justify-between gap-2"><span className="font-medium">{p.label}</span>{p.timing && <Pill tone="accent">{p.timing}</Pill>}</div>
                <div className="mt-1 text-sm text-ink-2">{p.reason}</div>
                <div className="text-xs text-muted">{p.impact}{p.volume ? ` · ${chf(p.volume)}` : ''}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  )
}
