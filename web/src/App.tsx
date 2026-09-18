import { ArrowLeft, Bot, Briefcase, Database, Languages, User } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type CrossGoalEffect, type GoalSpec, type LeverCard, type Overrides, type Overview, type PlanResponse, type Timeline, type TimelineGoal } from './api'
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
import { FactsPage } from './pages/FactsPage'
import { GoalsPage } from './pages/GoalsPage'
import { MainPage } from './pages/MainPage'

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

type Page = 'goals' | 'main' | 'facts' | 'pro'

function Shell({ lang, setLang }: { lang: string; setLang: (l: string) => void }) {
  const { t } = useT()
  const [clients, setClients] = useState<{ id: string; name: string }[]>([])
  const [clientId, setClientId] = useState<string | null>(null)
  const [page, setPage] = useState<Page>('goals')
  const [factsFrom, setFactsFrom] = useState<Page>('goals')
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
  const autoPlanned = useRef(new Set<string>())   // goals whose action plan we already pre-selected once
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [whyCard, setWhyCard] = useState<LeverCard | null>(null)
  const [ideasLoading, setIdeasLoading] = useState<Record<string, boolean>>({})
  const ideasAsked = useRef(new Set<string>())    // goals whose AI ideas we already requested

  useEffect(() => {
    api.clients().then((cs) => { setClients(cs); setClientId((cur) => cur ?? cs[0]?.id ?? null) })
    api.meta().then((m) => setLlm(m.llm))
  }, [])

  const confirmed = useMemo(() => overview?.goals.filter((g) => g.status !== 'suggested') ?? [], [overview])

  useEffect(() => {
    if (!clientId) return
    api.overview(clientId, lang).then((ov) => {
      setOverview(ov)
      const ok = ov.goals.filter((g) => g.status !== 'suggested')
      setGoalId((g) => (g && ok.some((x) => x.id === g) ? g : ok[0]?.id ?? null))
    })
  }, [clientId, lang, version])

  useEffect(() => {
    setActive([]); setOverrides({}); setPlan(null); setTimeline(null); setPage('goals'); setView('client')
    autoPlanned.current.clear(); ideasAsked.current.clear(); setIdeasLoading({})
  }, [clientId])
  useEffect(() => { if (page === 'pro') setOverrides((o) => ({ global: o.global ?? {} })) }, [goalId, page])

  // Main page: every confirmed goal on one timeline. At-risk goals get their proposal ticked once, and AI ideas.
  useEffect(() => {
    if (!clientId || page !== 'main') return
    const ctrl = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true); setError(null)
      try {
        const tl = await api.timeline(clientId, { active, overrides, lang }, ctrl.signal)
        setTimeline(tl)
        setLoading(false)
        const fresh = tl.goals.filter((g) => g.at_risk && !autoPlanned.current.has(`tl:${g.id}`))
        fresh.forEach((g) => autoPlanned.current.add(`tl:${g.id}`))
        const add = fresh.flatMap((g) => g.proposal).filter((i) => !active.includes(i))
        if (add.length) setActive((a) => [...a, ...add.filter((i) => !a.includes(i))])
        for (const g of tl.goals.filter((x) => x.at_risk && !ideasAsked.current.has(x.id))) {
          ideasAsked.current.add(g.id)
          setIdeasLoading((s) => ({ ...s, [g.id]: true }))
          api.goalIdeas(clientId, g.id, lang).then((r) => {
            if (r.ids.length) { setActive((a) => [...a, ...r.ids.filter((i) => !a.includes(i))]); setVersion((v) => v + 1) }
          }).catch(() => {}).finally(() => setIdeasLoading((s) => ({ ...s, [g.id]: false })))
        }
      } catch (e) {
        if (!ctrl.signal.aborted) { setError(String(e)); setLoading(false) }
      }
    }, 150)
    return () => { clearTimeout(timer); ctrl.abort() }
  }, [clientId, active, overrides, lang, version, page])

  // Re-simulate on every change (main and pro pages); hold the previous render (dimmed) while the new one loads.
  useEffect(() => {
    if (!clientId || !goalId || page !== 'pro') return
    const ctrl = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const body = { goal_id: goalId, active, overrides, lang }
        const p = await api.plan(clientId, { ...body, include_cross_goal: false }, ctrl.signal)
        setPlan(p)
        setLoading(false)
        if (!autoPlanned.current.has(goalId) && active.length === 0 && p.plan.length) {
          autoPlanned.current.add(goalId)       // first visit: show the goal with the action plan applied
          setActive(p.plan)
          return
        }
        autoPlanned.current.add(goalId)
        setCrossLoading(true)
        const c = await api.crossGoal(clientId, body, ctrl.signal)
        setCross(c)
        setCrossLoading(false)
      } catch (e) {
        if (!ctrl.signal.aborted) { setError(String(e)); setLoading(false); setCrossLoading(false) }
      }
    }, 150)
    return () => { clearTimeout(timer); ctrl.abort() }
  }, [clientId, goalId, active, overrides, lang, version, page])

  const toggle = useCallback((id: string, on: boolean) => setActive((a) => (on ? [...a.filter((x) => x !== id), id] : a.filter((x) => x !== id))), [])
  const setOverride = useCallback((scope: string, key: string, value: number | null) => {
    setOverrides((o) => {
      const next = { ...o, [scope]: { ...(o[scope] ?? {}) } }
      if (value === null) delete next[scope][key]
      else next[scope][key] = value
      return next
    })
  }, [])
  const addLever = useCallback((id: string) => { setActive((a) => (a.includes(id) ? a : [...a, id])); setVersion((v) => v + 1) }, [])
  const moveGoal = useCallback(async (g: TimelineGoal) => {
    const spec = overview?.goals.find((x) => x.id === g.id)
    if (!clientId || !spec || !g.move_to) return
    const { status_info: _drop, ...goal } = spec
    void _drop
    await api.upsertGoal(clientId, g.type === 'retirement'
      ? { ...goal, params: { ...goal.params, retirement_age: g.move_to.retirement_age ?? goal.params.retirement_age } }
      : { ...goal, target_date: g.move_to.date })
    setVersion((v) => v + 1)
  }, [clientId, overview])
  const openFacts = () => { setFactsFrom(page); setPage('facts') }

  const whyLever = useMemo(() => (why && why !== 'global' ? plan?.levers.find((l) => l.lever_id === why) : undefined), [why, plan])
  const planReady = page === 'main' ? !!timeline : plan && goalId && plan.goal.id === goalId

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
          {page === 'pro' && (
            <div className="flex rounded-lg border border-line p-0.5 text-sm">
              <button onClick={() => setView('client')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'client' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><User size={14} />{t('ui.client_view')}</button>
              <button onClick={() => setView('advisor')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'advisor' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><Briefcase size={14} />{t('ui.advisor_view')}</button>
              <button onClick={() => setView('data')} className={`inline-flex items-center gap-1 rounded-md px-2.5 py-1 ${view === 'data' ? 'bg-surface-2 font-medium' : 'text-ink-2'}`}><Database size={14} />{t('ui.data_view', {}, 'Data')}</button>
            </div>
          )}
          <button onClick={() => setLang(lang === 'en' ? 'de' : 'en')} className="inline-flex items-center gap-1 rounded-lg border border-line px-2.5 py-1.5 text-sm" aria-label="Language">
            <Languages size={14} />{lang === 'en' ? 'DE' : 'EN'}
          </button>
          {llm && (
            <span title={llm.model ?? ''} className={`hidden items-center gap-1 text-xs sm:inline-flex ${llm.available ? 'text-llm' : 'text-muted'}`}>
              <Bot size={14} />{llm.available ? llm.provider : t('ui.ai_off', {}, 'AI off')}
            </span>
          )}
        </div>
        {overview && page === 'pro' && view !== 'data' && confirmed.length > 0 && (
          <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-4 pb-2">
            {confirmed.map((g) => (
              <button key={g.id} onClick={() => setGoalId(g.id)}
                className={`flex shrink-0 items-center gap-2 rounded-full border px-3 py-1 text-sm ${g.id === goalId ? 'border-accent bg-accent-wash text-accent' : 'border-line text-ink-2 hover:bg-surface-2'}`}>
                {g.status_info && <span className={`h-2 w-2 rounded-full ${g.status_info.p_success >= 0.7 ? 'bg-good' : 'bg-warning'}`} aria-hidden />}
                {g.label}
                {g.status_info && <span className="text-xs text-muted tabular">{g.status_info.futures_of_10}/10</span>}
              </button>
            ))}
          </div>
        )}
      </header>

      {error && <div className="mx-auto mt-4 max-w-5xl rounded-xl border border-critical/40 bg-critical/10 p-3 text-sm text-critical">{error}</div>}
      {!clientId || !overview ? (
        <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>
      ) : page === 'goals' ? (
        <GoalsPage clientId={clientId} name={overview.client.name?.split(' ')[0] ?? ''}
          onContinue={(id) => { setGoalId(id); setVersion((v) => v + 1); setPage('main') }} onFacts={openFacts} />
      ) : page === 'facts' ? (
        <FactsPage clientId={clientId} overrides={overrides} onOverrides={setOverrides} onChanged={() => setVersion((v) => v + 1)}
          onBack={() => setPage(factsFrom === 'facts' ? 'goals' : factsFrom)} />
      ) : !planReady ? (
        <div className="p-10 text-ink-2">{t('ui.thinking', {}, 'Loading…')}</div>
      ) : page === 'main' ? (
        <MainPage clientId={clientId} tl={timeline!} active={active} loading={loading} ideasLoading={ideasLoading}
          onToggle={toggle} onWhy={setWhyCard} onLever={addLever} onMove={moveGoal}
          onPro={() => setPage('pro')} onFacts={openFacts} onGoals={() => setPage('goals')} />
      ) : (
        <main className="mx-auto max-w-7xl space-y-4 px-4 py-4">
          <div className="flex flex-wrap items-center gap-4 text-sm">
            <button onClick={() => setPage('main')} className="inline-flex items-center gap-1 text-accent hover:underline"><ArrowLeft size={14} />{t('flow.simple_view', {}, 'Simple view')}</button>
            <button onClick={openFacts} className="inline-flex items-center gap-1 text-accent hover:underline"><Database size={14} />{t('flow.see_data', {}, "See the data we're working with")}</button>
          </div>
          {view === 'advisor' ? (
            <AdvisorView clientId={clientId} goalId={goalId!} />
          ) : view === 'data' ? (
            <DataInsightsView clientId={clientId} overview={overview} />
          ) : (
            <>
              <div>
                <h2 className="mb-2 text-sm font-semibold text-ink-2">{t('ui.where_you_stand')} · {overview.client.name}</h2>
                <StandTiles ov={overview} />
              </div>
              <div className={`grid gap-4 transition-opacity lg:grid-cols-12 ${loading ? 'opacity-60' : ''}`}>
                <div className="lg:col-span-7">
                  <GoalCard plan={plan!} cross={cross} crossLoading={crossLoading} anyActive={active.length > 0}
                    onWhy={() => setWhy('global')}
                    onEditGoal={async (g: GoalSpec) => { await api.upsertGoal(clientId, g); setVersion((v) => v + 1) }} />
                  <div className="mt-4"><SpendingCard ov={overview} /></div>
                  {overview.risk && <div className="mt-4"><RiskCard risk={overview.risk} /></div>}
                </div>
                <div className="lg:col-span-5">
                  <LeverPanel plan={plan!} onToggle={toggle} onUsePlan={() => setActive(plan!.plan)} onClear={() => setActive([])}
                    onWhy={setWhy}
                    onRemove={async (id) => { await api.removeLever(clientId, id); setActive((a) => a.filter((x) => x !== id)); setVersion((v) => v + 1) }}>
                    <WhatIfBox clientId={clientId} goalId={goalId!} onLever={addLever} />
                  </LeverPanel>
                </div>
              </div>
            </>
          )}
        </main>
      )}

      {whyCard && page === 'main' && (
        <WhyDrawer title={whyCard.title} description={whyCard.description} sideEffects={whyCard.side_effects}
          assumptions={whyCard.assumptions} lever={whyCard}
          onChange={(k, v) => setOverride(whyCard.lever_id, k, v)} onClose={() => setWhyCard(null)} />
      )}
      {why && plan && page === 'pro' && (
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
