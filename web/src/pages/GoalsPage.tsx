import { ArrowRight, Check, CircleHelp, Database, House, LoaderCircle, Pencil, SendHorizontal, Sparkles, Target, TreePalm, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type GoalSpec } from '../api'
import { GoalEditor } from '../components/GoalEditor'
import { chf, monthLabel } from '../format'
import { useT } from '../i18n'

const ICON = { home: House, retirement: TreePalm, target: Target } as const

function meta(g: GoalSpec, months: string[]): string {
  const amount = g.type === 'home' ? Number(g.params.price) : g.type === 'target' ? Number(g.params.amount) : null
  const when = g.type === 'retirement' ? `${g.params.retirement_age}` : monthLabel(g.target_date, months)
  return [amount ? chf(amount) : null, when].filter(Boolean).join(' · ')
}

/** One goal as an oval: desaturated while it's only a suggestion, in color once the client confirms it. */
function GoalChip({ g, onConfirm, onEdit, onDelete }: { g: GoalSpec; onConfirm: () => void; onEdit: () => void; onDelete: () => void }) {
  const { t, months } = useT()
  const Icon = ICON[g.type as keyof typeof ICON] ?? Target
  const suggested = g.status === 'suggested'
  const origin = g.origin === 'ai' ? t('flow.from_ai', {}, 'AI idea') : g.origin === 'data' ? t('flow.from_data', {}, 'From your data') : ''
  return (
    <span title={[origin, g.note].filter(Boolean).join(': ')}
      className={`group inline-flex max-w-full items-center gap-1.5 rounded-full border py-1 pr-1 pl-2.5 text-sm transition ${suggested
        ? 'border-dashed border-line bg-surface-2 text-ink-2 grayscale'
        : 'border-accent bg-accent-wash text-accent'}`}>
      {g.origin === 'ai' && suggested ? <Sparkles size={13} className="shrink-0" aria-hidden /> : <Icon size={14} className="shrink-0" aria-hidden />}
      <span className="truncate font-medium">{g.label}</span>
      <span className="hidden text-xs opacity-75 sm:inline">{meta(g, months())}</span>
      {suggested && (
        <button onClick={onConfirm} className="rounded-full p-1 hover:bg-good/15 hover:text-good-text" aria-label={t('flow.confirm', {}, 'Confirm')} title={t('flow.confirm', {}, 'Confirm')}>
          <Check size={14} />
        </button>
      )}
      <button onClick={onEdit} className="rounded-full p-1 hover:bg-surface" aria-label={t('flow.edit', {}, 'Edit')} title={t('flow.edit', {}, 'Edit')}><Pencil size={13} /></button>
      <button onClick={onDelete} className="rounded-full p-1 hover:bg-critical/10 hover:text-critical" aria-label={t('flow.delete', {}, 'Delete')} title={t('flow.delete', {}, 'Delete')}><X size={14} /></button>
    </span>
  )
}

/** Page 1: "Tell us your financial goal". Suggestions from the data and the AI, confirmed or written by the client. */
export function GoalsPage({ clientId, name, onContinue, onFacts }: {
  clientId: string; name: string; onContinue: (goalId: string) => void; onFacts: () => void
}) {
  const { t, lang } = useT()
  const [goals, setGoals] = useState<GoalSpec[]>([])
  const [thinking, setThinking] = useState(false)
  const [text, setText] = useState('')
  const [question, setQuestion] = useState<{ text: string; original: string } | null>(null)
  const [answer, setAnswer] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [help, setHelp] = useState(false)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true
    setGoals([]); setQuestion(null); setError(null); setEditing(null)
    api.goals(clientId).then((g) => { if (live) setGoals(g) })
    setThinking(true)
    api.suggestGoals(clientId, lang).then((g) => { if (live) setGoals(g) }).catch(() => {}).finally(() => live && setThinking(false))
    return () => { live = false }
  }, [clientId, lang])

  const save = async (g: GoalSpec) => setGoals(await api.upsertGoal(clientId, g))
  const remove = async (g: GoalSpec) => { setGoals(await api.deleteGoal(clientId, g.id)); if (editing === g.id) setEditing(null) }

  const send = async (sentence: string, q?: { text: string; original: string }, reply?: string) => {
    if (!sentence.trim()) return
    setBusy(true); setError(null)
    try {
      const r = await api.draftGoal(clientId, { text: sentence, lang, ...(q ? { question: q.text, answer: reply } : {}) })
      if (r.status === 'question') { setQuestion({ text: r.question, original: sentence }); setAnswer('') }
      else if (r.status === 'goal') { setGoals(await api.goals(clientId)); setText(''); setQuestion(null) }
      else setError(r.message)
    } catch (e) { setError(String(e)) } finally { setBusy(false); input.current?.focus() }
  }

  const confirmed = goals.filter((g) => g.status !== 'suggested')
  const editingGoal = goals.find((g) => g.id === editing)

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="text-sm text-ink-2">{t('flow.hello', { name }, `Hello ${name}`)}</div>
      <h1 className="mt-1 flex items-center gap-2 text-3xl font-semibold tracking-tight">
        {t('flow.goals_title', {}, 'Tell us your financial goal')}
        <button onClick={() => setHelp(!help)} className="rounded-full p-1 text-muted hover:text-ink" aria-label="Help"><CircleHelp size={18} /></button>
      </h1>
      {help && <p className="mt-2 max-w-xl text-sm text-ink-2">{t('flow.goals_help', {}, 'We suggested a few goals from your account data. Confirm the ones that fit, edit or remove the others, or write your own in plain words: "a car in one year", "retire at 60", "a flat in Zurich for 900k".')}</p>}

      <div className="mt-6 rounded-2xl border border-line bg-surface p-3 shadow-sm focus-within:border-accent">
        <div className="flex flex-wrap items-center gap-2">
          {goals.map((g) => (
            <GoalChip key={g.id} g={g} onConfirm={() => save({ ...g, status: 'confirmed' })}
              onEdit={() => setEditing(editing === g.id ? null : g.id)} onDelete={() => remove(g)} />
          ))}
          {thinking && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line px-3 py-1 text-sm text-muted">
              <LoaderCircle size={14} className="animate-spin" />{t('flow.thinking', {}, 'Finding ideas for you…')}
            </span>
          )}
          <form className="flex min-w-[14rem] flex-1 items-center gap-2" onSubmit={(e) => { e.preventDefault(); send(text) }}>
            <input ref={input} value={text} onChange={(e) => setText(e.target.value)} disabled={busy || !!question}
              placeholder={t('flow.placeholder', {}, 'I want to buy a car in one year…')}
              className="min-w-0 flex-1 bg-transparent px-1 py-1.5 text-base outline-none placeholder:text-muted" />
            <button type="submit" disabled={busy || !text.trim() || !!question} aria-label={t('flow.add', {}, 'Add')}
              className="rounded-full bg-accent p-2 text-white disabled:opacity-30">
              {busy && !question ? <LoaderCircle size={16} className="animate-spin" /> : <SendHorizontal size={16} />}
            </button>
          </form>
        </div>
      </div>

      {editingGoal && (
        <GoalEditor goal={editingGoal} onCancel={() => setEditing(null)}
          onSave={(g) => { setEditing(null); save({ ...g, status: 'confirmed' }) }} />
      )}

      {question && (
        <form className="mt-3 rounded-xl border border-llm/40 bg-llm-wash p-3" onSubmit={(e) => { e.preventDefault(); send(question.original, question, answer) }}>
          <div className="flex items-center gap-1.5 text-sm font-medium text-llm"><Sparkles size={14} />{t('flow.one_question', {}, 'One question')}</div>
          <div className="mt-1 text-sm">{question.text}</div>
          <div className="mt-2 flex gap-2">
            <input autoFocus value={answer} onChange={(e) => setAnswer(e.target.value)} disabled={busy}
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
            <button type="submit" disabled={busy || !answer.trim()} className="rounded-lg bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-30">
              {busy ? <LoaderCircle size={16} className="animate-spin" /> : t('flow.answer', {}, 'Answer')}
            </button>
            <button type="button" onClick={() => setQuestion(null)} className="rounded-lg px-2 text-sm text-ink-2 hover:bg-surface">{t('ui.cancel', {}, 'Cancel')}</button>
          </div>
        </form>
      )}
      {error && <div className="mt-3 text-sm text-critical">{error}</div>}

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <button disabled={!confirmed.length} onClick={() => onContinue(confirmed[0].id)}
          className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 font-medium text-white shadow-sm disabled:opacity-30">
          {t('flow.continue', {}, 'Show me my plan')}<ArrowRight size={18} />
        </button>
        <span className="text-sm text-muted">
          {confirmed.length ? t('flow.n_confirmed', { n: confirmed.length }, `${confirmed.length} goal(s) confirmed`)
            : t('flow.confirm_hint', {}, 'Confirm at least one goal with ✓')}
        </span>
        <button onClick={onFacts} className="ml-auto inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
          <Database size={14} />{t('flow.see_data', {}, "See the data we're working with")}
        </button>
      </div>

      <p className="mt-10 max-w-2xl text-[11px] leading-snug text-muted">
        {t('flow.disclaimer', {}, 'We use AI. Suggestions combine the data the bank has about you, public data (prices, statistics) and what you tell us. They are estimates you can change; the projections are computed, not written by the AI.')}
      </p>
    </div>
  )
}
