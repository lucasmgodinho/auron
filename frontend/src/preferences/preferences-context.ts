import { createContext } from 'react'

import type { SupportedLocale } from '../i18n'

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

export type PreferencesContextValue = {
  locale: SupportedLocale
  setLocale: (locale: SupportedLocale) => void
  theme: ThemePreference
  resolvedTheme: ResolvedTheme
  setTheme: (theme: ThemePreference) => void
}

export const PreferencesContext = createContext<PreferencesContextValue | undefined>(undefined)
