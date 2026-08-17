import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { LOCALE_STORAGE_KEY, type SupportedLocale } from '../i18n'
import {
  PreferencesContext,
  type ResolvedTheme,
  type ThemePreference,
} from './preferences-context'

const THEME_STORAGE_KEY = 'auron-theme'
const darkModeQuery = '(prefers-color-scheme: dark)'

function readLocale(): SupportedLocale {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY) === 'en' ? 'en' : 'pt-BR'
  } catch {
    return 'pt-BR'
  }
}

function readTheme(): ThemePreference {
  try {
    const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY)
    return savedTheme === 'light' || savedTheme === 'dark' || savedTheme === 'system'
      ? savedTheme
      : 'system'
  } catch {
    return 'system'
  }
}

function resolveTheme(theme: ThemePreference): ResolvedTheme {
  if (theme !== 'system') return theme
  return window.matchMedia(darkModeQuery).matches ? 'dark' : 'light'
}

type PreferencesProviderProps = { children: ReactNode }

export function PreferencesProvider({ children }: PreferencesProviderProps) {
  const { i18n } = useTranslation()
  const [locale, setLocaleState] = useState<SupportedLocale>(readLocale)
  const [theme, setThemeState] = useState<ThemePreference>(readTheme)
  const [resolvedTheme, setResolvedTheme] = useState<ResolvedTheme>(() => resolveTheme(readTheme()))

  useEffect(() => {
    const media = window.matchMedia(darkModeQuery)
    const applyTheme = () => {
      const resolved = theme === 'system' ? (media.matches ? 'dark' : 'light') : theme
      setResolvedTheme(resolved)
      document.documentElement.dataset.theme = resolved
      document.documentElement.style.colorScheme = resolved
    }

    applyTheme()
    if (theme === 'system') media.addEventListener('change', applyTheme)
    return () => media.removeEventListener('change', applyTheme)
  }, [theme])

  useEffect(() => {
    document.documentElement.lang = locale
    if (i18n.language !== locale) void i18n.changeLanguage(locale)
  }, [i18n, locale])

  function setTheme(nextTheme: ThemePreference) {
    setThemeState(nextTheme)
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme)
    } catch {
      // The preference remains active for this page when storage is unavailable.
    }
  }

  function setLocale(nextLocale: SupportedLocale) {
    setLocaleState(nextLocale)
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, nextLocale)
    } catch {
      // The preference remains active for this page when storage is unavailable.
    }
  }

  const value = useMemo(
    () => ({ locale, setLocale, theme, resolvedTheme, setTheme }),
    [locale, resolvedTheme, theme],
  )

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>
}
