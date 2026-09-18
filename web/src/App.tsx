import { Bot, Briefcase, Database, Languages, User } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type CrossGoalEffect, type GoalSpec, type Overrides, type Overview, type PlanResponse } from './api'
import { AdvisorView } from './components/AdvisorView'
import { DataInsightsView } from './components/DataInsightsView'
import { GoalCard } from './components/GoalCard'
import { LeverPanel } from './components/LeverPanel'
import { RiskCard } from './components/RiskCard'
import { SpendingCard } from './components/SpendingCard'
import { StandTiles } from './components/StandTiles'
import { WhatIfBox } from './components/WhatIfBox'
import { WhyDrawer } from './components/WhyDrawer'
import { I18nContext, useT, type Strings } from './i18n'

function stored(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback } catch { return fallback }
}
function store(key: string, value: string) {
  try { localStorage.setItem(key, value) } catch { /* private mode */ }
}

/** Type-to-search over thousands of clients (population data); starred demo clients come first. */
function ClientPicker({ clients, clientId, onPick }: { clients: { id: string; name: string }[]; clientId: string | null; onPick: (id: string) => void }) {
  const [text, setText] = useState('')
  const byName = useMemo(() => new Map(clients.map((c) => [c.name, c.id])), [clients])
  const current = clients.find((c) => c.id === clientId)
  return (
    <>
      <input list="client-list" value={text} placeholder={current?.name ?? ''} title={current?.name}
        onChange={(e) => {
          const id = byName.get(e.target.value)
          if (id) { onPick(id); setText('') } else setText(e.target.value)
        }}
        className="w-80 max-w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm placeholder:text-ink" />
      <datalist id="client-list">{clients.map((c) => <option key={c.id} value={c.name} />)}</datalist>
    </>
  )
}

export default function App() {
  const [lang, setLang] = useState(() => stored('mygoal.lang', 'en'))
  const [strings, setStrings] = useState<Strings>({})
  useEffect(() => { api.i18n(lang).then(setStrings); store('mygoal.lang', lang); document.documentElement.lang = lang }, [lang])
  return (
    <I18nContext.Provider value={{ lang, strings }}>
      <Shell lang={lang} setLang={setLang} />
    </I18nContext.Provider>
  )
}

function Shell({ lang, setLang }: { lang: string; setLang: (l: string) => void }) {
  const { t } = useT()
  const [clients, setClients] = useState<{ id: string; name: string }[]>([])
  const [clientId, setClientId] = useState<string | null>(null)
  const [overview, setOverview] = useState<Overview | null>(null)
  const [goalId, setGoalId] = useState<string | null>(null)
  const [active, setActive] = useState<string[]>([])
  const [overrides, setOverrides] = useState<Overrides>({})
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cross, setCross] = useState<CrossGoalEffect[]>([])
  const [crossLoading, setCrossLoading] = useState(false)
  const [why, setWhy] = useState<string | null>(null)
  const [view, setView] = useState<'client' | 'advisor' | 'data'>('client')
  const [version, setVersion] = useState(0)
  const [llm, setLlm] = useState<{ available: boolean; provider: string | null; model: string | null } | null>(null)

  useEffect(() => {
    api.clients().then((cs) => { setClients(cs); setClientId((cur) => cur ?? cs[0]?.id ?? null) })
    api.meta().then((m) => setLlm(m.llm))
  }, [])

  useEffect(() => {
    if (!clientId) return
    api.overview(clientId, lang).then((ov) => {
      setOverview(ov)
      setGoalId((g) => (g && ov.goals.some((x) => x.id === g) ? g : ov.goals[0]?.id ?? null))
    })
  }, [clientId, lang, version])

  useEffect(() => { setActive([]); setOverrides({}); setPlan(null) }, [clientId])
  useEffect(() => { setActive([]); setOverrides((o) => ({ global: o.global ?? {} })) }, [goalId])

  // Re-simulate on every change; hold the previous render (dimmed) while the new one loads.
  useEffect(() => {
    if (!clientId || !goalId) return
    const ctrl = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const body = { goal_id: goalId, active, overrides, lang }
        const p = await api.plan(clientId, { ...body, include_cross_goal: false }, ctrl.signal)
        setPlan(p)
        setLoading(false)
        setCrossLoading(true)
        const c = await api.crossGoal(clientId, body, ctrl.signal)
        setCross(c)
        setCrossLoading(false)
      } catch (e) {
        if (!ctrl.signal.aborted) { setError(String(e)); setLoading(false); setCrossLoading(false) }
      }
    }, 150)
    return () => { clearTimeout(timer); ctrl.abort() }
  }, [clientId, goalId, active, overrides, lang, version])

  const toggle = useCallback((id: string, on: boolean) => setActive((a) => (on ? [...a.filter((x) => x !== id), id] : a.filter((x) => x !== id))), [])
  const setOverride = useCallback((scope: string, key: string, value: number | null) => {
    setOverrides((o) => {
      const next = { ...o, [scope]: { ...(o[scope] ?? {}) } }
      if (value === null) delete next[scope][key]
      else next[scope][key] = value
      return next
    })
  }, [])

  const whyLever = useMemo(() => (why && why !== 'global' ? plan?.levers.find((l) => l.lever_id === why) : undefined), [why, plan])

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-line bg-page/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-3">
          <div className="mr-auto">
            <div className="text-lg font-semibold leading-tight">{t('ui.title')}</div>
            <div className="text-xs text-ink-2">{t('ui.subtitle')}</div>
          </div>
          {clients.length > 30 ? (
            <ClientPicker clients={clients} clientId={clientId} onPick={setClientId} />
          ) : clients.length > 1 && (
            <select value={clientId ?? ''} onChange={(e) => setClientId(e.target.value)} className="rounded-lg border border-line bg-surface px-2 py-1.5 text-sm">
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <div className="flex rounded-lg border border-line p-0.5 text-sm">
            <button onClick={() => setView('client')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'client' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><User size={14} />{t('ui.client_view')}</button>
            <button onClick={() => setView('advisor')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'advisor' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><Briefcase size={14} />{t('ui.advisor_view')}</button>
            <button onClick={() => setView('data')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'data' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><Database size={14} />{t('ui.data_view', {}, 'Data')}</button>
          </div>
          <button onClick={() => setLang(lang === 'en' ? 'de' : 'en')} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-sm" aria-label="Language">
            <Languages size={14} />{lang === 'en' ? 'DE' : 'EN'}
          </button>
          {llm && (
            <span title={llm.model ?? ''} className={`hidden items-center gap-1 text-xs sm:inline-flex ${llm.available ? 'text-llm' : 'text-muted'}`}>
              <Bot size={14} />{llm.available ? llm.provider : t('ui.ai_off', {}, 'AI off')}
            </span>
          )}
        </div>
        {overview && view !== 'data' && (
          <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-4 pb-2">
            {overview.goals.map((g) => (
              <button key={g.id} onClick={() => setGoalId(g.id)}
                className={`flex shrink-0 items-center gap-2 rounded-full border px-3 py-1 text-sm ${g.id === goalId ? 'border-accent bg-accent-wash text-accent' : 'border-line text-ink-2 hover:bg-surface-2'}`}>
                <span className={`h-2 w-2 rounded-full ${g.status.p_success >= 0.7 ? 'bg-good' : 'bg-warning'}`} aria-hidden />
                {g.label}
                <span className="text-xs text-muted tabular">{g.status.futures_of_10}/10</span>
              </button>
            ))}
          </div>
        )}
      </header>

      <main className="mx-auto max-w-7xl space-y-4 px-4 py-4">
        {error && <div className="rounded-xl border border-critical/40 bg-critical/10 p-3 text-sm text-critical">{error}</div>}
        {!overview || !clientId ? (
          <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>
        ) : view === 'advisor' && goalId ? (
          <AdvisorView clientId={clientId} goalId={goalId} />
        ) : view === 'data' ? (
          <DataInsightsView clientId={clientId} overview={overview} />
        ) : (
          <>
            <div>
              <h2 className="mb-2 text-sm font-semibold text-ink-2">{t('ui.where_you_stand')} · {overview.client.name}</h2>
              <StandTiles ov={overview} />
            </div>
            {plan && goalId ? (
              <div className={`grid gap-4 transition-opacity lg:grid-cols-12 ${loading ? 'opacity-60' : ''}`}>
                <div className="lg:col-span-7">
                  <GoalCard plan={plan} cross={cross} crossLoading={crossLoading} anyActive={active.length > 0}
                    onWhy={() => setWhy('global')}
                    onEditGoal={async (g: GoalSpec) => { await api.upsertGoal(clientId, g); setVersion((v) => v + 1) }} />
                  <div className="mt-4"><SpendingCard ov={overview} /></div>
                  {overview.risk && <div className="mt-4"><RiskCard risk={overview.risk} /></div>}
                </div>
                <div className="lg:col-span-5">
                  <LeverPanel plan={plan} onToggle={toggle} onUsePlan={() => setActive(plan.plan)} onClear={() => setActive([])}
                    onWhy={setWhy}
                    onRemove={async (id) => { await api.removeLever(clientId, id); setActive((a) => a.filter((x) => x !== id)); setVersion((v) => v + 1) }}>
                    <WhatIfBox clientId={clientId} goalId={goalId}
                      onLever={(id) => { setActive((a) => (a.includes(id) ? a : [...a, id])); setVersion((v) => v + 1) }} />
                  </LeverPanel>
                </div>
              </div>
            ) : (
              <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>
            )}
          </>
        )}
      </main>

      {why && plan && (
        why === 'global' ? (
          <WhyDrawer title={t('ui.assumptions')} assumptions={plan.assumptions} notes={overview?.data_quality}
            onChange={(k, v) => setOverride('global', k, v)} onClose={() => setWhy(null)} />
        ) : whyLever ? (
          <WhyDrawer title={whyLever.title} description={whyLever.description} sideEffects={whyLever.side_effects}
            assumptions={whyLever.assumptions} lever={whyLever}
            onChange={(k, v) => setOverride(whyLever.lever_id, k, v)} onClose={() => setWhy(null)} />
        ) : null
      )}
    </div>
  )
}
