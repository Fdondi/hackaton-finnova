import { ArrowDownLeft, ArrowLeft, ArrowUpRight, Check, LoaderCircle, Pencil, Plus, RotateCcw, SendHorizontal, Sparkles, Trash2, Wallet, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type Fact, type Facts, type FactsReading, type Overrides } from '../api'
import { Card, SourceBadge } from '../components/ui'
import { chf } from '../format'
import { useT } from '../i18n'

const percent = (unit: string) => unit === 'share' || unit.startsWith('%')

/** One line of the list: what it is, the value, where it comes from, and an inline editor. */
function FactRow({ f, onSave }: { f: Fact; onSave: (id: string, value: number | string | null) => Promise<void> }) {
  const { t } = useT()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const toInput = () => (f.input === 'number' && typeof f.value === 'number' ? String(percent(f.unit) ? +(f.value * 100).toFixed(2) : f.value) : String(f.value ?? ''))
  const [draft, setDraft] = useState(toInput)
  const save = async (value: number | string | null) => {
    setBusy(true)
    try { await onSave(f.id, value); setEditing(false) } finally { setBusy(false) }
  }
  const submit = () => save(f.input === 'number' ? (draft === '' ? null : Number(draft) / (percent(f.unit) ? 100 : 1)) : draft)
  const kindDot = f.kind === 'known' ? 'bg-accent' : f.kind === 'yours' ? 'bg-good' : 'bg-llm'
  return (
    <li className="group border-b border-line py-2.5 last:border-0">
      <div className="flex items-start gap-3">
        <span className={`mt-2 h-2 w-2 shrink-0 rounded-full ${kindDot}`} title={t(`flow.kind_${f.kind}`, {}, f.kind)} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span className="text-sm text-ink-2">{f.label}</span>
            {!editing && <span className="text-sm font-semibold tabular">{f.display}</span>}
          </div>
          {editing ? (
            <form className="mt-1.5 flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit() }}>
              <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} type={f.input === 'number' ? 'number' : 'text'}
                step="any" className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1 text-sm tabular" />
              {f.input === 'number' && <span className="text-xs text-muted">{percent(f.unit) ? '%' : f.unit.replace('CHF/', 'CHF / ')}</span>}
              <button type="submit" disabled={busy} className="rounded-lg bg-accent p-1.5 text-white">{busy ? <LoaderCircle size={14} className="animate-spin" /> : <Check size={14} />}</button>
              <button type="button" onClick={() => setEditing(false)} className="rounded-lg p-1.5 text-ink-2 hover:bg-surface-2"><X size={14} /></button>
            </form>
          ) : (
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {f.source && f.source_label && <SourceBadge source={f.source} label={f.source_label} />}
              {f.note && <span className="text-xs text-muted">{f.note}</span>}
              {f.editable && (
                <button onClick={() => { setDraft(toInput()); setEditing(true) }} className="inline-flex items-center gap-1 text-xs text-accent opacity-70 hover:underline group-hover:opacity-100">
                  <Pencil size={11} />{t('flow.edit', {}, 'Edit')}
                </button>
              )}
              {f.source === 'user' && f.id.startsWith('a:') && (
                <button onClick={() => save(null)} className="inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><RotateCcw size={11} />{t('ui.reset', {}, 'reset')}</button>
              )}
              {f.id.startsWith('n:') && (
                <button onClick={() => save('')} className="inline-flex items-center gap-1 text-xs text-muted hover:text-critical"><Trash2 size={11} />{t('ui.remove', {}, 'Remove')}</button>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}

/** "See the data we're working with": what we know, what we assume, what you told us. Edit a line or just tell us. */
export function FactsPage({ clientId, overrides, onOverrides, onChanged, onBack }: {
  clientId: string; overrides: Overrides; onOverrides: (o: Overrides) => void; onChanged: () => void; onBack: () => void
}) {
  const { t, lang } = useT()
  const [facts, setFacts] = useState<Facts | null>(null)
  const [reading, setReading] = useState<FactsReading | null>(null)
  const [readingBusy, setReadingBusy] = useState(false)
  const [newFact, setNewFact] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [chat, setChat] = useState<{ who: 'you' | 'ai'; text: string }[]>([])
  const [chatBusy, setChatBusy] = useState(false)

  useEffect(() => { api.facts(clientId, overrides, lang).then(setFacts) }, [clientId, overrides, lang])
  const loadReading = () => {
    setReadingBusy(true)
    api.factsReading(clientId, lang).then(setReading).catch(() => setReading(null)).finally(() => setReadingBusy(false))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadReading, [clientId, lang])

  const edit = async (id: string, value: number | string | null) => {
    const r = await api.editFact(clientId, id, value, overrides, lang)
    setFacts(r.facts)
    onOverrides(r.overrides)
    if (!id.startsWith('a:')) { onChanged(); setReading(null); loadReading() }
  }
  const send = async () => {
    if (!message.trim()) return
    const text = message
    setChat((c) => [...c, { who: 'you', text }]); setMessage(''); setChatBusy(true)
    try {
      const r = await api.factsChat(clientId, text, overrides, lang)
      setChat((c) => [...c, { who: 'ai', text: r.reply }])
      setFacts(r.facts)
      onOverrides(r.overrides)
      onChanged()
    } catch (e) {
      setChat((c) => [...c, { who: 'ai', text: String(e) }])
    } finally { setChatBusy(false) }
  }

  if (!facts) return <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>
  const s = facts.summary
  return (
    <div className="mx-auto max-w-4xl space-y-4 px-4 py-6 pb-40">
      <button onClick={onBack} className="inline-flex items-center gap-1 text-sm text-accent hover:underline"><ArrowLeft size={14} />{t('flow.back', {}, 'Back')}</button>
      <h1 className="text-2xl font-semibold">{t('flow.facts_title', {}, "The data we're working with")}</h1>
      <p className="max-w-2xl text-sm text-ink-2">{t('flow.facts_intro', {}, 'What we know from your accounts, what we assume, and what you told us. Change any line, or tell us in your own words at the bottom.')}</p>

      <Card className="p-5">
        <h2 className="font-semibold">{t('flow.financial_facts', {}, 'Financial facts')}</h2>
        <div className="mt-3 grid grid-cols-[1fr_auto_1fr_auto_1fr] items-center gap-2 text-center">
          <div className="rounded-xl bg-surface-2 p-3">
            <div className="flex items-center justify-center gap-1 text-xs text-ink-2"><ArrowDownLeft size={14} />{t('flow.money_in', {}, 'Money in / month')}</div>
            <div className="text-xl font-semibold tabular">{chf(s.money_in)}</div>
          </div>
          <span className="text-2xl text-muted">−</span>
          <div className="rounded-xl bg-surface-2 p-3">
            <div className="flex items-center justify-center gap-1 text-xs text-ink-2"><ArrowUpRight size={14} />{t('flow.money_out', {}, 'Money out / month')}</div>
            <div className="text-xl font-semibold tabular">{chf(s.money_out)}</div>
          </div>
          <span className="text-2xl text-muted">=</span>
          <div className={`rounded-xl p-3 ${s.free_cash >= 0 ? 'bg-accent-wash' : 'bg-critical/10'}`}>
            <div className="flex items-center justify-center gap-1 text-xs text-ink-2"><Wallet size={14} />{t('flow.free_cash', {}, 'Free cash / month')}</div>
            <div className={`text-xl font-semibold tabular ${s.free_cash >= 0 ? 'text-accent' : 'text-critical'}`}>{chf(s.free_cash)}</div>
          </div>
        </div>
        <ul className="mt-3">{facts.money.map((f) => <FactRow key={f.id} f={f} onSave={edit} />)}</ul>
      </Card>

      <Card className="p-5">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">{t('flow.life_facts', {}, 'Life facts')}</h2>
          <div className="flex gap-3 text-xs text-ink-2">
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-accent" />{t('flow.kind_known', {}, 'we know')}</span>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-llm" />{t('flow.kind_assumed', {}, 'we assume')}</span>
            <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-good" />{t('flow.kind_yours', {}, 'you told us')}</span>
          </div>
        </div>
        <div className="mt-3 rounded-xl border border-llm/30 bg-llm-wash p-3">
          <div className="flex items-center gap-1.5 text-sm font-medium text-llm"><Sparkles size={14} />{t('flow.ai_reading', {}, 'What the AI reads in your data')}</div>
          {readingBusy && <div className="mt-1 flex items-center gap-1.5 text-sm text-ink-2"><LoaderCircle size={14} className="animate-spin" />{t('flow.reading', {}, 'Reading…')}</div>}
          {!readingBusy && reading?.available === false && <div className="mt-1 text-sm text-ink-2">{t('ui.ai_off', {}, 'AI off')}</div>}
          {!readingBusy && reading?.summary && <p className="mt-1 text-sm">{reading.summary}</p>}
          {!readingBusy && !!reading?.observations.length && (
            <ul className="mt-2 space-y-1 text-sm">
              {reading.observations.map((o) => (
                <li key={o.text} className="flex items-start gap-2">
                  <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-llm" />
                  <span className="flex-1" title={o.basis}>{o.text}</span>
                  <button onClick={() => setMessage(`${t('flow.not_quite', {}, 'Not quite')}: "${o.text}" — `)} className="shrink-0 text-xs text-muted hover:text-ink">{t('flow.correct_it', {}, 'correct it')}</button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <ul className="mt-2">{[...facts.life, ...facts.notes].map((f) => <FactRow key={f.id} f={f} onSave={edit} />)}</ul>
        {newFact === null ? (
          <button onClick={() => setNewFact('')} className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-dashed border-line px-3 py-1 text-sm text-ink-2 hover:bg-surface-2">
            <Plus size={14} />{t('flow.add_fact', {}, 'Add something we should know')}
          </button>
        ) : (
          <form className="mt-2 flex gap-2" onSubmit={async (e) => { e.preventDefault(); await edit('n:new', newFact); setNewFact(null) }}>
            <input autoFocus value={newFact} onChange={(e) => setNewFact(e.target.value)} placeholder={t('flow.add_fact_ph', {}, 'e.g. we plan to move to Zurich next year')}
              className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm" />
            <button type="submit" className="rounded-lg bg-accent px-3 text-sm text-white">{t('flow.add', {}, 'Add')}</button>
            <button type="button" onClick={() => setNewFact(null)} className="rounded-lg px-2 text-sm text-ink-2">{t('ui.cancel', {}, 'Cancel')}</button>
          </form>
        )}
      </Card>

      <Card className="p-5">
        <h2 className="font-semibold">{t('flow.future_assumptions', {}, 'What we assume about the future')}</h2>
        <ul className="mt-2">{facts.future.map((f) => <FactRow key={f.id} f={f} onSave={edit} />)}</ul>
        {facts.data_notes.length > 0 && (
          <ul className="mt-3 space-y-1 border-t border-line pt-3 text-xs text-muted">{facts.data_notes.map((n) => <li key={n.message}>{n.message}</li>)}</ul>
        )}
      </Card>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-page/95 backdrop-blur">
        <div className="mx-auto max-w-4xl px-4 py-3">
          {chat.length > 0 && (
            <div className="mb-2 max-h-40 space-y-1.5 overflow-y-auto text-sm">
              {chat.map((m, i) => (
                <div key={i} className={`flex ${m.who === 'you' ? 'justify-end' : ''}`}>
                  <span className={`max-w-[80%] rounded-2xl px-3 py-1.5 ${m.who === 'you' ? 'bg-accent text-white' : 'bg-llm-wash'}`}>{m.text}</span>
                </div>
              ))}
            </div>
          )}
          <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); send() }}>
            <input value={message} onChange={(e) => setMessage(e.target.value)} disabled={chatBusy}
              placeholder={t('flow.chat_ph', {}, "Tell us what's different: \"my gross salary is 118k\", \"we're expecting a baby\"…")}
              className="min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 py-2 text-sm" />
            <button type="submit" disabled={chatBusy || !message.trim()} className="rounded-xl bg-accent p-2.5 text-white disabled:opacity-30">
              {chatBusy ? <LoaderCircle size={16} className="animate-spin" /> : <SendHorizontal size={16} />}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
