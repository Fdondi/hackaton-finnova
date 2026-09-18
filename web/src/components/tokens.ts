import { useEffect, useState } from 'react'

const VARS = ['--series-1', '--series-2', '--muted', '--grid', '--axis', '--ink', '--ink-2', '--surface', '--critical', '--good'] as const

/** Chart colors are CSS tokens; SVG attributes need resolved values, re-read when the color scheme flips. */
export function useTokens() {
  const read = () => Object.fromEntries(VARS.map((v) => [v, getComputedStyle(document.documentElement).getPropertyValue(v).trim()]))
  const [tokens, setTokens] = useState<Record<string, string>>(read)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const on = () => setTokens(read())
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return tokens
}
