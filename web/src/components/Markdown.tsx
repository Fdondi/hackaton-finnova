import type { ReactNode } from 'react'

/** Inline Markdown the AI tends to write: **bold**, *italic* / _italic_, `code`. Built as elements, never raw HTML. */
function inline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|`[^`]+`)/g
  let last = 0
  for (const m of text.matchAll(re)) {
    if (m.index! > last) out.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('**') || tok.startsWith('__')) out.push(<strong key={out.length}>{tok.slice(2, -2)}</strong>)
    else if (tok.startsWith('`')) out.push(<code key={out.length} className="rounded bg-surface-2 px-1 text-[0.9em]">{tok.slice(1, -1)}</code>)
    else out.push(<em key={out.length}>{tok.slice(1, -1)}</em>)
    last = m.index! + tok.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** Paragraphs, bullet and numbered lists, headings flattened to bold lines. Enough for chat answers. */
export function Markdown({ text, className = '' }: { text: string; className?: string }) {
  const blocks: ReactNode[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flush = () => {
    if (!list) return
    const Tag = list.ordered ? 'ol' : 'ul'
    blocks.push(<Tag key={blocks.length} className={`${list.ordered ? 'list-decimal' : 'list-disc'} space-y-0.5 pl-5`}>
      {list.items.map((it, i) => <li key={i}>{inline(it)}</li>)}
    </Tag>)
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const bullet = line.match(/^[-*•]\s+(.*)$/)
    const numbered = line.match(/^\d+[.)]\s+(.*)$/)
    if (bullet || numbered) {
      const ordered = !!numbered
      if (!list || list.ordered !== ordered) { flush(); list = { ordered, items: [] } }
      list.items.push((bullet ?? numbered)![1])
      continue
    }
    flush()
    if (!line) continue
    const heading = line.match(/^#{1,6}\s+(.*)$/)
    blocks.push(<p key={blocks.length} className={heading ? 'font-semibold' : ''}>{inline(heading ? heading[1] : line)}</p>)
  }
  flush()
  return <div className={`space-y-1.5 ${className}`}>{blocks}</div>
}
