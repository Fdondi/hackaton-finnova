import { Check, ChevronDown, ClipboardCopy, ClipboardPaste, ExternalLink, Handshake, LoaderCircle, Plug, TriangleAlert, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Integrations, type ScenarioImport } from '../api'
import { useT } from '../i18n'

async function copyText(text: string, fallback: HTMLTextAreaElement | null): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    if (!fallback) return false
    fallback.select()
    return document.execCommand('copy')
  }
}

/** "422 {"detail": "..."}" -> "..." */
function errorText(e: unknown): string {
  const raw = String(e).replace(/^Error: \d+ /, '')
  try { return String(JSON.parse(raw).detail ?? raw) } catch { return raw }
}

/** Exactly what went out or came back, as indented JSON. */
function JsonView({ summary, value, children }: { summary: string; value: unknown; children?: ReactNode }) {
  return (
    <details className="text-xs">
      <summary className="cursor-pointer text-muted hover:text-ink">{summary}</summary>
      {children}
      <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-surface-2 p-2 font-mono text-[11px] leading-snug break-words whitespace-pre-wrap text-ink-2">{JSON.stringify(value, null, 2)}</pre>
    </details>
  )
}

function Result({ r }: { r: ScenarioImport }) {
  const { t } = useT()
  const fixRef = useRef<HTMLTextAreaElement>(null)
  const [copied, setCopied] = useState(false)
  return (
    <div className="space-y-1.5 rounded-lg border border-line bg-surface p-2">
      {r.ids.length > 0 && (
        <p className="text-sm">
          <Check size={14} className="mr-1 inline text-good-text" />
          {r.ids.length === 1
            ? t('partners.added_one', { source: r.source }, `1 option from ${r.source} is in the list above.`)
            : t('partners.added', { n: r.ids.length, source: r.source }, `${r.ids.length} options from ${r.source} are in the list above.`)}
          {r.pick_one && r.ids.length > 1 && <span className="text-ink-2"> {t('partners.pick_one', {}, 'You can switch on one of them at a time.')}</span>}
        </p>
      )}
      {r.note && <p className="text-xs text-ink-2">{r.source}: {r.note}</p>}
      {r.rejected.length > 0 && (
        <div className="space-y-1">
          <p className="inline-flex items-center gap-1 text-xs font-medium text-critical"><TriangleAlert size={12} />{t('partners.rejected', { n: r.rejected.length }, `${r.rejected.length} could not be read:`)}</p>
          <ul className="list-disc pl-5 text-xs text-ink-2">{r.rejected.map((x, i) => <li key={i}>{x.title ? <b>{x.title}: </b> : null}{x.error}</li>)}</ul>
          {r.fix_prompt && (
            <>
              <textarea ref={fixRef} readOnly value={r.fix_prompt} className="sr-only" aria-hidden tabIndex={-1} />
              <button onClick={async () => { if (await copyText(r.fix_prompt!, fixRef.current)) { setCopied(true); setTimeout(() => setCopied(false), 1500) } }}
                className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1 text-xs font-medium hover:bg-surface-2">
                {copied ? <Check size={12} /> : <ClipboardCopy size={12} />}{t('partners.copy_fix', {}, 'Copy a correction for them')}
              </button>
            </>
          )}
        </div>
      )}
      <JsonView summary={t('partners.what_came_back', {}, 'What came back')} value={r.received} />
    </div>
  )
}

/** The "manual API": options from other companies' assistants become actions (off until ticked).
 *  Connected integrations are listed first, with exactly what they receive. For any other assistant: a fixed text to
 *  copy into its chat (the client is logged in there, so it carries no data about them) and a box for its answer.
 *  New integrations are connected from their address once we've checked they speak the format. */
export function ScenarioBox({ clientId, goalId, onScenarios }: { clientId: string; goalId: string; onScenarios: (ids: string[]) => void }) {
  const { t, lang } = useT()
  const [open, setOpen] = useState(true)
  const [prompt, setPrompt] = useState('')
  const [integ, setInteg] = useState<Integrations | null>(null)
  const [paste, setPaste] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, ScenarioImport>>({})   // per integration id, and 'paste'
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [copied, setCopied] = useState(false)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const origin = window.location.origin

  useEffect(() => { api.partnerPrompt(lang).then((r) => setPrompt(r.prompt)).catch(() => setPrompt('')) }, [lang])
  useEffect(() => { api.integrations(clientId, lang).then(setInteg).catch(() => setInteg(null)) }, [clientId, lang])

  const run = async <T,>(key: string, p: Promise<T>, then: (r: T) => void) => {
    setBusy(key); setErrors((e) => ({ ...e, [key]: '' }))
    try { then(await p) } catch (e) { setErrors((x) => ({ ...x, [key]: errorText(e) })) } finally { setBusy(null) }
  }
  const imported = (key: string) => (r: ScenarioImport) => {
    setResults((x) => ({ ...x, [key]: r }))
    if (r.ids.length) onScenarios(r.ids)
  }
  const err = (key: string) => errors[key] && <p className="text-xs text-critical">{errors[key]}</p>

  return (
    <div className="rounded-xl border border-line bg-surface-2/40 p-3">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2 text-left text-sm font-medium">
        <Handshake size={16} className="text-ink-2" aria-hidden />
        <span className="flex-1">{t('partners.title', {}, 'Options from other companies')}</span>
        <ChevronDown size={14} className={`text-muted transition ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="mt-3 space-y-4 text-sm">
          {!!integ?.connected.length && (
            <section className="space-y-2">
              <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t('partners.connected', {}, 'Connected')}</h3>
              {integ.connected.map((c) => (
                <div key={c.id} className="space-y-1.5 rounded-lg border border-line bg-surface p-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Plug size={14} className="text-ink-2" aria-hidden />
                    <span className="font-medium">{c.name}</span>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted">{c.url ?? t('partners.built_in', {}, 'demo, built in')}</span>
                    <button disabled={!!busy} onClick={() => run(c.id, api.askIntegration(clientId, c.id, { goal_id: goalId, lang }), imported(c.id))}
                      className="inline-flex items-center gap-1 rounded-lg bg-accent px-2.5 py-1 text-xs font-medium text-white disabled:opacity-50">
                      {busy === c.id ? <LoaderCircle size={12} className="animate-spin" /> : <Handshake size={12} />}{t('partners.ask', {}, 'Ask for options')}
                    </button>
                    <button onClick={() => run(`x:${c.id}`, api.disconnectIntegration(clientId, c.id, lang), setInteg)} className="rounded p-1 text-muted hover:text-critical"
                      aria-label={t('partners.disconnect', {}, 'Disconnect')} title={t('partners.disconnect', {}, 'Disconnect')}><X size={14} /></button>
                  </div>
                  <JsonView summary={t('partners.what_we_send', {}, 'What we send')} value={c.sends}>
                    <p className="mt-1 text-muted">{t('partners.sends_note', {}, 'The question, the format, your language, and the account link you set up with them. Nothing from your bank account.')}</p>
                  </JsonView>
                  {err(c.id)}
                  {results[c.id] && <Result r={results[c.id]} />}
                </div>
              ))}
            </section>
          )}

          <section className="space-y-1.5">
            <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{t('partners.any_assistant', {}, 'Any other assistant')}</h3>
            <p className="text-xs text-ink-2">{t('partners.copy_hint', {}, "Copy this into the other assistant's chat, where you're logged in, and paste its answer below. It contains nothing about you.")}</p>
            <div className="relative">
              <textarea ref={promptRef} readOnly value={prompt} rows={4} onFocus={(e) => e.currentTarget.select()}
                className="w-full resize-y rounded-lg border border-line bg-surface p-2 pr-20 font-mono text-xs text-ink-2" />
              <button onClick={async () => { if (await copyText(prompt, promptRef.current)) { setCopied(true); setTimeout(() => setCopied(false), 1500) } }}
                className="absolute top-2 right-2 inline-flex items-center gap-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs font-medium hover:bg-surface-2">
                {copied ? <Check size={12} /> : <ClipboardCopy size={12} />}{copied ? t('partners.copied', {}, 'Copied') : t('partners.copy', {}, 'Copy')}
              </button>
            </div>
            <textarea value={paste} onChange={(e) => setPaste(e.target.value)} rows={3} placeholder={t('partners.paste_placeholder', {}, 'Paste their answer here')}
              className="w-full resize-y rounded-lg border border-line bg-surface p-2 font-mono text-xs text-ink placeholder:text-muted focus:border-accent focus:outline-none" />
            <button disabled={!!busy || !paste.trim()} onClick={() => run('paste', api.importScenarios(clientId, { goal_id: goalId, text: paste, lang }), (r) => {
              imported('paste')(r)
              if (!r.rejected.length) setPaste('')
            })} className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 font-medium text-white disabled:opacity-40">
              {busy === 'paste' ? <LoaderCircle size={14} className="animate-spin" /> : <ClipboardPaste size={14} />}{t('partners.add', {}, 'Add as actions')}
            </button>
            {err('paste')}
            {results.paste && <Result r={results.paste} />}
          </section>

          <details className="rounded-lg border border-dashed border-line p-2">
            <summary className="cursor-pointer text-sm font-medium">{t('partners.connect_title', {}, 'Connect a new integration')}</summary>
            <div className="mt-2 space-y-2 text-xs text-ink-2">
              <p className="font-medium text-ink">{t('partners.how_to_tell', {}, 'How to tell if another AI works with this:')}</p>
              <ul className="list-disc space-y-1.5 pl-5">
                <li><b>{t('partners.m_chat', {}, "Chat assistants (your insurer's chatbot, ChatGPT, …).")}</b>{' '}
                  {t('partners.m_chat_how', {}, 'Compatible if it can read a pasted message and answer with a block of JSON; almost all can. Nothing to connect: use copy and paste above. If part of the answer can’t be read, you get a correction to send back.')}</li>
                <li><b>{t('partners.m_api', {}, 'Company APIs.')}</b>{' '}
                  {t('partners.m_api_how', {}, 'Compatible if the company publishes a "mygoal.scenarios/v1" description: look for it in their developer docs or app settings, or at https://<their site>/.well-known/mygoal-scenarios. Paste the address below: we check it, add the company to your list, and show exactly what it will receive.')}</li>
              </ul>
              <form className="flex gap-2" onSubmit={(e) => {
                e.preventDefault()
                run('connect', api.connectIntegration(clientId, url, lang), (r) => { setInteg(r); setUrl('') })
              }}>
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/.well-known/mygoal-scenarios"
                  className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink placeholder:text-muted focus:border-accent focus:outline-none" />
                <button type="submit" disabled={!!busy || !url.trim()} className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-surface-2 disabled:opacity-40">
                  {busy === 'connect' ? <LoaderCircle size={14} className="animate-spin" /> : <Plug size={14} />}{t('partners.connect', {}, 'Check and connect')}
                </button>
              </form>
              {err('connect')}
              {!!integ?.demo_addresses.length && (
                <p className="text-muted">{t('partners.demo', {}, 'Demo:')}{' '}
                  {integ.demo_addresses.map((a) => (
                    <button key={a} type="button" onClick={() => setUrl(origin + a)} className="mr-2 font-mono text-accent hover:underline">{origin + a}</button>
                  ))}
                </p>
              )}
              <a href="/api/scenario-format" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent hover:underline">
                <ExternalLink size={12} />{t('partners.for_developers', {}, 'The format, for developers')}
              </a>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}
