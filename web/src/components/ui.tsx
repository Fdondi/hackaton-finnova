import {
  Baby, Briefcase, Building2, Car, CircleX, Heart, HeartPulse, House, Landmark, Scissors, Sparkles, Split, Target, TrendingUp,
  type LucideIcon,
} from 'lucide-react'
import type { ReactNode } from 'react'
import type { Source } from '../api'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl border border-line bg-surface ${className}`}>{children}</section>
}

type Tone = 'good' | 'bad' | 'neutral' | 'accent' | 'llm'
const TONES: Record<Tone, string> = {
  good: 'bg-good/10 text-good-text',
  bad: 'bg-critical/10 text-critical',
  neutral: 'bg-surface-2 text-ink-2',
  accent: 'bg-accent-wash text-accent',
  llm: 'bg-llm-wash text-llm',
}

export function Pill({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-10 shrink-0 rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${checked ? 'bg-accent' : 'bg-grid'}`}
    >
      <span className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`} />
    </button>
  )
}

const SOURCE_TONE: Record<Source, Tone> = {
  transactions: 'accent', client_data: 'accent', user: 'good', market_default: 'neutral', llm_estimate: 'llm',
  population: 'accent',
}

export function SourceBadge({ source, label }: { source: Source; label: string }) {
  return <Pill tone={SOURCE_TONE[source]}>{label}</Pill>
}

const ICONS: Record<string, LucideIcon> = {
  'trending-up': TrendingUp, landmark: Landmark, 'x-circle': CircleX, scissors: Scissors, building: Building2,
  home: House, target: Target, car: Car, 'heart-pulse': HeartPulse, baby: Baby, heart: Heart, split: Split,
  briefcase: Briefcase,
}

export function LeverIcon({ name, origin }: { name: string | null; origin: string }) {
  const Icon = origin === 'agent' ? Sparkles : (name && ICONS[name]) || Target
  return (
    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${origin === 'agent' ? 'bg-llm-wash text-llm' : 'bg-accent-wash text-accent'}`}>
      <Icon size={18} aria-hidden />
    </span>
  )
}

export function Button({ children, onClick, variant = 'ghost', disabled, type = 'button', title }: {
  children: ReactNode; onClick?: () => void; variant?: 'primary' | 'ghost' | 'outline'; disabled?: boolean; type?: 'button' | 'submit'; title?: string
}) {
  const styles = {
    primary: 'bg-accent text-white hover:opacity-90',
    ghost: 'text-ink-2 hover:bg-surface-2',
    outline: 'border border-line text-ink hover:bg-surface-2',
  }[variant]
  return (
    <button type={type} title={title} disabled={disabled} onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:opacity-40 ${styles}`}>
      {children}
    </button>
  )
}
