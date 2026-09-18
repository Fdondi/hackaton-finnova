/** "7 of 10 futures": ten markers, filled for the futures that reach the goal in time. */
export function Futures({ n, label }: { n: number; label: string }) {
  return (
    <div className="flex items-center gap-3" role="img" aria-label={label}>
      <div className="flex gap-1">
        {Array.from({ length: 10 }, (_, i) => (
          <span key={i} className={`h-3.5 w-3.5 rounded-full ${i < n ? (n >= 7 ? 'bg-good' : 'bg-accent') : 'border-2 border-grid'}`} />
        ))}
      </div>
      <span className="text-sm text-ink-2">{label}</span>
    </div>
  )
}
