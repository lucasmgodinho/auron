import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { en } from './locales/en'
import { ptBR } from './locales/pt-BR'

export const supportedLocales = ['pt-BR', 'en'] as const
export type SupportedLocale = (typeof supportedLocales)[number]

export const LOCALE_STORAGE_KEY = 'auron-locale'

function initialLocale(): SupportedLocale {
  try {
    const savedLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY)
    return savedLocale === 'en' || savedLocale === 'pt-BR' ? savedLocale : 'pt-BR'
  } catch {
    return 'pt-BR'
  }
}

void i18n.use(initReactI18next).init({
  resources: {
    'pt-BR': { translation: ptBR },
    en: { translation: en },
  },
  lng: initialLocale(),
  fallbackLng: 'pt-BR',
  interpolation: { escapeValue: false },
})

export default i18n
