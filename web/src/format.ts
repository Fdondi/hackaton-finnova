export function chf(x: number | null | undefined): string {
  if (x === null || x === undefined || Number.isNaN(x)) return '–'
  const sign = x < 0 ? '−' : ''
  return `${sign}CHF ${Math.round(Math.abs(x)).toLocaleString('en-US').replace(/,/g, '’')}`
}

export function chfCompact(x: number): string {
  const a = Math.abs(x)
  if (a >= 1_000_000) return `${(x / 1_000_000).toFixed(1)}M`
  if (a >= 1_000) return `${Math.round(x / 1_000)}k`
  return `${Math.round(x)}`
}

export function monthLabel(iso: string | null | undefined, months: string[]): string {
  if (!iso) return '–'
  const [y, m] = iso.split('-').map(Number)
  return `${months[m - 1]} ${y}`
}

export function monthsBetween(a: string, b: string): number {
  const [ya, ma] = a.split('-').map(Number)
  const [yb, mb] = b.split('-').map(Number)
  return (yb - ya) * 12 + (mb - ma)
}

export function formatValue(value: number, unit: string): string {
  if (unit === 'share' || unit.startsWith('%')) return `${(value * 100).toFixed(value * 100 < 10 && value !== 0 ? 1 : 0)}%${unit.startsWith('%/') ? unit.slice(1) : ''}`
  if (unit.startsWith('CHF')) return `${chf(value)}${unit.slice(3)}`
  return `${Number.isInteger(value) ? value.toLocaleString('en-US').replace(/,/g, '’') : value.toFixed(2)} ${unit}`
}
