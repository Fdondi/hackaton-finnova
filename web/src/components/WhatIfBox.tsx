import { Bot, Check, ChevronDown, LoaderCircle, Send, Sparkles, X } from 'lucide-react'
import { useState } from 'react'
import { api, type WhatIfResult } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'
import { Markdown } from './Markdown'
import { MonthlyFigure } from './WhyDrawer'

interface Conversation { key: number; text: string; busy: boolean; result: WhatIfResult | null; answer: string; error: string | null }

/** Research a reasonable number for a question the assistant just asked. */
export function SuggestValueButton({ clientId, question, context, onPick }: {
  clientId: string; question: string; context?: string; onPick: (value: string, reason: string) => void
}) {
  const { t, lang } = useT()
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const run = async () => {
    setBusy(true); setError(null)
    try {
      const r = await api.suggestValue(clientId, { question, context: context ?? '', lang })
      if (!r.available || r.value === undefined || r.value === null) {
        setError(t('flow.suggest_unavailable', {}, 'No suggestion available (AI is off).'))
        return
      }
      onPick(String(r.value), r.reason ?? '')
      setHint(r.reason ?? null)
    } catch (e) {
      setError(String(e))
    } finally { setBusy(false) }
  }
  return (
    <div className="w-full">
      <button type="button" onClick={run} disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-llm/50 px-2.5 py-1 text-xs text-llm hover:bg-llm-wash disabled:opacity-50">
        {busy ? <LoaderCircle size={12} className="animate-spin" /> : <Sparkles size={12} />}
        {t('flow.suggest_value', {}, 'Suggest a value')}
      </button>
      {hint && <p className="mt-1 text-xs text-ink-2">{hint}</p>}
      {error && <p className="mt-1 text-xs text-critical">{error}</p>}
    </div>
  )
}

/** One what-if as a provisional action: its conversation, the resulting action, and Accept / Discard. */
function ProvisionalCard({ c, clientId, onAnswer, onAccept, onDiscard }: {
  c: Conversation; clientId: string; onAnswer: (answer: string) => void; onAccept: () => void; onDiscard: () => void
}) {
  const { t } = useT()
  const [answer, setAnswer] = useState(c.answer)
  const [steps, setSteps] = useState(false)
  const r = c.result
  const done = r && (r.status === 'lever' || r.status === 'existing_lever') && r.lever_id
  return (
    <li className="rounded-xl border border-dashed border-llm/60 bg-surface p-3 text-sm">
      <div className="flex items-start gap-2">
        <Sparkles size={14} className="mt-0.5 shrink-0 text-llm" />
        <div className="min-w-0 flex-1 font-medium">{c.text}</div>
        <button onClick={onDiscard} className="rounded p-0.5 text-muted hover:text-critical" aria-label={t('flow.discard', {}, 'Discard')} title={t('flow.discard', {}, 'Discard')}><X size={14} /></button>
      </div>
      {c.busy && <div className="mt-2 flex items-center gap-1.5 text-ink-2"><LoaderCircle size={14} className="animate-spin" />{t('flow.working', {}, 'Working on it…')}</div>}
      {c.error && <p className="mt-2 text-xs text-critical">{c.error}</p>}
      {r && (
        <div className="mt-2 space-y-2">
          {r.steps.length > 0 && (
            <button onClick={() => setSteps(!steps)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink">
              <ChevronDown size={12} className={steps ? 'rotate-180' : ''} />{t('flow.how_ai_worked', { n: r.steps.length }, `${r.steps.length} steps`)}
            </button>
          )}
          {steps && (
            <ol className="space-y-0.5 text-xs text-muted">
              {r.steps.map((s, i) => <li key={i} className="flex gap-1.5"><Bot size={12} className="mt-0.5 shrink-0" /><span className="font-medium whitespace-nowrap">{s.name.replace(/_/g, ' ')}</span><span>{s.summary}</span></li>)}
            </ol>
          )}
          {r.status === 'question' && r.question && !c.busy && (
            <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); onAnswer(answer) }}>
              <span className="w-full"><Markdown text={r.question.text} /></span>
              {r.question.options.length > 0 ? (
                <select value={answer} onChange={(e) => setAnswer(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5">
                  <option value="" />{r.question.options.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : (
                <input autoFocus value={answer} onChange={(e) => setAnswer(e.target.value)} inputMode={r.question.kind === 'number' ? 'decimal' : 'text'}
                  className="w-40 rounded-lg border border-line bg-surface px-2 py-1.5 tabular" />
              )}
              {r.question.unit && <span className="text-ink-2">{r.question.unit}</span>}
              <button type="submit" className="rounded-lg bg-accent px-3 py-1.5 font-medium text-white">OK</button>
              {r.question.kind !== 'choice' && (
                <SuggestValueButton clientId={clientId} question={r.question.text} context={c.text}
                  onPick={(v) => setAnswer(v)} />
              )}
            </form>
          )}
          {r.status !== 'question' && r.message && (
            <Markdown text={r.message} className={r.status === 'unsupported' || r.status === 'error' ? 'text-ink-2' : ''} />
          )}
          {r.evaluation && (
            <div>
              <p className="text-xs text-ink-2">
                {r.evaluation.months_gained ? `${Math.abs(r.evaluation.months_gained) === 1
                  ? (r.evaluation.months_gained > 0 ? t('lever.month_gained', {}, '1 month sooner') : t('lever.month_lost', {}, '1 month later'))
                  : r.evaluation.months_gained > 0 ? t('lever.months_gained', { months: r.evaluation.months_gained }) : t('lever.months_lost', { months: -r.evaluation.months_gained })} · ` : ''}
                {r.evaluation.monthly_equivalent !== 0 && `${r.evaluation.monthly_equivalent > 0 ? '+' : ''}${chf(r.evaluation.monthly_equivalent)}/${t('ui.month_short', {}, 'mo')}`}
                {r.evaluation.how_the_monthly_figure_comes_about?.once
                  ? `${r.evaluation.monthly_equivalent !== 0 ? ' · ' : ''}${chf(r.evaluation.how_the_monthly_figure_comes_about.once)} ${t('flow.once_short', {}, 'once')}`
                  : r.evaluation.monthly_equivalent === 0 ? `${chf(0)}/${t('ui.month_short', {}, 'mo')}` : ''}
              </p>
              {r.evaluation.how_the_monthly_figure_comes_about && (
                <MonthlyFigure b={r.evaluation.how_the_monthly_figure_comes_about} />
              )}
            </div>
          )}
          {done && (
            <div className="flex gap-2">
              <button onClick={onAccept} className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 font-medium text-white"><Check size={14} />{t('flow.accept_action', {}, 'Accept this action')}</button>
              <button onClick={onDiscard} className="rounded-lg px-3 py-1.5 text-ink-2 hover:bg-surface-2">{t('flow.discard', {}, 'Discard')}</button>
            </div>
          )}
        </div>
      )}
    </li>
  )
}

/** Free-text what-if. Each question becomes a provisional action card; the box is free again right away.
 *  Accepting a card hides the conversation and hands the action to the caller (ticked). */
export function WhatIfBox({ clientId, goalId, onLever }: { clientId: string; goalId: string; onLever: (leverId: string) => void }) {
  const { t, lang } = useT()
  const [text, setText] = useState('')
  const [convs, setConvs] = useState<Conversation[]>([])
  const patch = (key: number, p: Partial<Conversation>) => setConvs((cs) => cs.map((c) => (c.key === key ? { ...c, ...p } : c)))

  async function run(key: number, p: Promise<WhatIfResult>) {
    patch(key, { busy: true, error: null })
    try {
      const r = await p
      const d = r.question?.default
      patch(key, { busy: false, result: r, answer: d !== null && d !== undefined ? String(d) : '' })
    } catch (e) {
      patch(key, { busy: false, error: String(e) })
    }
  }
  const start = () => {
    const q = text.trim()
    if (!q) return
    const key = Date.now()
    setConvs((cs) => [{ key, text: q, busy: true, result: null, answer: '', error: null }, ...cs])
    setText('')
    run(key, api.whatif(clientId, goalId, q, lang))
  }
  const discard = (c: Conversation) => {
    setConvs((cs) => cs.filter((x) => x.key !== c.key))
    if (c.result?.status === 'lever' && c.result.lever_id) api.removeLever(clientId, c.result.lever_id).catch(() => {})
  }

  return (
    <div className="rounded-xl border-2 border-llm/50 bg-llm-wash p-3 shadow-sm">
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); start() }}>
        <div className="relative flex-1">
          <Sparkles size={16} className="absolute top-2.5 left-2.5 text-llm" aria-hidden />
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t('ui.whatif_placeholder')}
            className="w-full rounded-lg border border-llm/40 bg-surface py-2 pr-2 pl-8 text-sm text-ink placeholder:text-muted focus:border-llm focus:outline-none focus:ring-2 focus:ring-llm/30" />
        </div>
        <button type="submit" disabled={!text.trim()} className="inline-flex items-center gap-1 rounded-lg bg-llm px-3 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40">
          <Send size={14} />{t('ui.whatif_button')}
        </button>
      </form>
      {convs.length > 0 && (
        <ul className="mt-3 space-y-2">
          {convs.map((c) => (
            <ProvisionalCard key={c.key} c={c} clientId={clientId}
              onAnswer={(a) => c.result && run(c.key, api.answer(c.result.session_id, a))}
              onAccept={() => { if (c.result?.lever_id) onLever(c.result.lever_id); setConvs((cs) => cs.filter((x) => x.key !== c.key)) }}
              onDiscard={() => discard(c)} />
          ))}
        </ul>
      )}
    </div>
  )
}
