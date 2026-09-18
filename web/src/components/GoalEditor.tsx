import { useState } from 'react'
import type { GoalSpec } from '../api'
import { useT } from '../i18n'
import { Button } from './ui'

/** Minimal goal wizard: the one number and the date. Real data often has no goals, so the UI must collect them. */
export function GoalEditor({ goal, onSave, onCancel }: { goal: GoalSpec; onSave: (g: GoalSpec) => void; onCancel: () => void }) {
  const { t } = useT()
  const amountKey = goal.type === 'home' ? 'price' : goal.type === 'target' ? 'amount' : goal.type === 'retirement' ? 'retirement_age' : null
  const [label, setLabel] = useState(goal.label)
  const [amount, setAmount] = useState(amountKey ? Number(goal.params[amountKey] ?? 0) : 0)
  const [date, setDate] = useState(goal.target_date?.slice(0, 7) ?? '')
  return (
    <form className="mt-3 grid gap-3 rounded-xl border border-line p-3 sm:grid-cols-3"
      onSubmit={(e) => {
        e.preventDefault()
        const target_date = goal.type === 'retirement' ? null : date ? `${date}-01` : goal.target_date
        onSave({ ...goal, label, target_date, params: amountKey ? { ...goal.params, [amountKey]: amount } : goal.params })
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
        <label className="text-xs text-ink-2">{t('ui.target')}
          <input type="month" className="mt-1 w-full rounded-lg border border-line bg-surface px-2 py-1.5 text-sm text-ink" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
      )}
      <div className="flex gap-2 sm:col-span-3">
        <Button type="submit" variant="primary">{t('ui.save', {}, 'Save')}</Button>
        <Button onClick={onCancel}>{t('ui.cancel', {}, 'Cancel')}</Button>
      </div>
    </form>
  )
}
