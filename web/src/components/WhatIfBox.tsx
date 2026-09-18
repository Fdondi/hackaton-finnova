import { Bot, LoaderCircle, Send, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { api, type WhatIfResult } from '../api'
import { chf } from '../format'
import { useT } from '../i18n'

/** Free-text what-if. Routes to a specialist, the LLM agent, or the rules agent; the result becomes a normal lever. */
export function WhatIfBox({ clientId, goalId, onLever }: { clientId: string; goalId: string; onLever: (leverId: string) => void }) {
  const { t, lang } = useT()
  const [text, setText] = useState('')
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<WhatIfResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function run(p: Promise<WhatIfResult>) {
    setBusy(true)
    setError(null)
    try {
      const r = await p
      setResult(r)
      if (r.question?.default !== null && r.question?.default !== undefined) setAnswer(String(r.question.default))
      else setAnswer('')
      if ((r.status === 'lever' || r.status === 'existing_lever') && r.lever_id) onLever(r.lever_id)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 rounded-xl border-2 border-llm/50 bg-llm-wash p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-llm">
        <Sparkles size={16} aria-hidden />{t('ui.whatif_title', {}, 'Ask "what if" (AI)')}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) run(api.whatif(clientId, goalId, text.trim(), lang)) }}>
        <div className="relative flex-1">
          <Sparkles size={16} className="absolute top-2.5 left-2.5 text-llm" aria-hidden />
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t('ui.whatif_placeholder')}
            className="w-full rounded-lg border border-llm/40 bg-surface py-2 pr-2 pl-8 text-sm text-ink placeholder:text-muted focus:border-llm focus:outline-none focus:ring-2 focus:ring-llm/30" />
        </div>
        <button type="submit" disabled={busy || !text.trim()} className="inline-flex items-center gap-1 rounded-lg bg-llm px-3 text-sm font-medium text-white hover:opacity-90 disabled:opacity-40">
          {busy ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}{t('ui.whatif_button')}
        </button>
      </form>
      {error && <p className="mt-2 text-xs text-critical">{error}</p>}
      {result && (
        <div className="mt-3 space-y-2 text-sm">
          <ol className="space-y-0.5 text-xs text-muted">
            {result.steps.map((s, i) => (
              <li key={i} className="flex gap-1.5"><Bot size={12} className="mt-0.5 shrink-0" aria-hidden /><span className="font-medium whitespace-nowrap">{s.name.replace(/_/g, ' ')}</span><span>{s.summary}</span></li>
            ))}
          </ol>
          {result.status === 'question' && result.question && (
            <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); run(api.answer(result.session_id, answer)) }}>
              <span className="w-full font-medium">{result.question.text}</span>
              {result.question.options.length > 0 ? (
                <select value={answer} onChange={(e) => setAnswer(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5">
                  <option value="" />{result.question.options.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : (
                <input autoFocus value={answer} onChange={(e) => setAnswer(e.target.value)} inputMode={result.question.kind === 'number' ? 'decimal' : 'text'}
                  className="w-36 rounded-lg border border-line bg-surface px-2 py-1.5 tabular" />
              )}
              {result.question.unit && <span className="text-ink-2">{result.question.unit}</span>}
              <button type="submit" disabled={busy} className="rounded-lg bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40">OK</button>
            </form>
          )}
          {result.status !== 'question' && result.message && (
            <p className={result.status === 'unsupported' || result.status === 'error' ? 'text-ink-2' : 'font-medium'}>{result.message}</p>
          )}
          {result.evaluation && (
            <p className="text-xs text-ink-2">
              {result.evaluation.months_gained ? `${result.evaluation.months_gained > 0 ? t('lever.months_gained', { months: result.evaluation.months_gained }) : t('lever.months_lost', { months: -result.evaluation.months_gained })} · ` : ''}
              {chf(result.evaluation.monthly_equivalent)}/{t('ui.month_short', {}, 'mo')} · {t('ui.agent_' + result.agent, {}, result.agent)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
