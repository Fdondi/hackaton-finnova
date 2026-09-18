import { createContext, useContext } from 'react'

export type Strings = Record<string, unknown>

export const I18nContext = createContext<{ lang: string; strings: Strings }>({ lang: 'en', strings: {} })

/** Same strings the backend uses (mygoal/explain/i18n/<lang>.yaml), fetched once per language. */
export function useT() {
  const { lang, strings } = useContext(I18nContext)
  return {
    lang,
    t(key: string, vars: Record<string, string | number> = {}, fallback?: string): string {
      let node: unknown = strings
      for (const part of key.split('.')) {
        node = node && typeof node === 'object' ? (node as Record<string, unknown>)[part] : undefined
      }
      const template = typeof node === 'string' ? node : fallback ?? key
      return template.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? `{${k}}`))
    },
    months(): string[] {
      return (strings.months as string[]) ?? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    },
  }
}
