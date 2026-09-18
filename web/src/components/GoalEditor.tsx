import { useState } from 'react'
import type { GoalSpec } from '../api'
import { useT } from '../i18n'
import { Button } from './ui'

/** Minimal goal editor: name, the one number, the year (goal dates are June 1), and for targets spend vs keep saved. */
export function GoalEditor({ goal, onSave, onCancel }: { goal: GoalSpec; onSave: (g: GoalSpec) => void; onCancel: () => void }) {
  const { t } = useT()
  const amountKey = goal.type === 'home' ? 'price' : goal.type === 'target' ? 'amount' : goal.type === 'retirement' ? 'retirement_age' : null
  const [label, setLabel] = useState(goal.label)
  const [amount, setAmount] = useState(amountKey ? Number(goal.params[amountKey] ?? 0) : 0)
  const [year, setYear] = useState(goal.target_date?.slice(0, 4) ?? '')
  const [kind, setKind] = useState(String(goal.params.kind ?? 'spend'))
  return (
    <form className="mt-3 grid gap-3 rounded-xl border border-line bg-surface p-3 sm:grid-cols-4"
      onSubmit={(e) => {
        e.preventDefault()
        const target_date = goal.type === 'retirement' ? null : year ? `${year}-06-01` : goal.target_date
        const params = { ...goal.params, ...(amountKey ? { [amountKey]: amount } : {}), ...(goal.type === 'target' ? { kind } : {}) }
        onSave({ ...goal, label, target_date, params })
      }}>
      <label className="text-xs text-ink-2">{t('ui.goal_name', {}, 'Name')}
        <input className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink" value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      {amountKey && (
        <label className="text-xs text-ink-2">{amountKey === 'retirement_age' ? t('ui.age', {}, 'Age') : 'CHF'}
          <input type="number" className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink tabular" value={amount}
            step={amountKey === 'retirement_age' ? 1 : 1000} onChange={(e) => setAmount(Number(e.target.value))} />
        </label>
      )}
      {goal.type !== 'retirement' && (
        <label className="text-xs text-ink-2">{t('flow.year', {}, 'Year')}
          <input type="number" min={2000} max={2100} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink tabular"
            value={year} onChange={(e) => setYear(e.target.value)} />
        </label>
      )}
      {goal.type === 'target' && (
        <label className="text-xs text-ink-2">{t('flow.money_at_date', {}, 'At that date the money is…')}
          <select value={kind} onChange={(e) => setKind(e.target.value)} className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink">
            <option value="spend">{t('flow.kind_spend', {}, 'spent (a car, a trip)')}</option>
            <option value="save">{t('flow.kind_save', {}, 'kept saved (a fund, a reserve)')}</option>
          </select>
        </label>
      )}
      <div className="flex gap-2 sm:col-span-4">
        <Button type="submit" variant="primary">{t('ui.save', {}, 'Save')}</Button>
        <Button onClick={onCancel}>{t('ui.cancel', {}, 'Cancel')}</Button>
      </div>
    </form>
  )
}
