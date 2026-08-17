import { useTranslation } from 'react-i18next'

import type { SupportedLocale } from '../i18n'
import type { ThemePreference } from '../preferences/preferences-context'
import { usePreferences } from '../preferences/usePreferences'

export function PreferenceControls() {
  const { t } = useTranslation()
  const { locale, setLocale, theme, setTheme } = usePreferences()

  return (
    <div className="preference-controls">
      <label className="preference-field">
        <span>{t('common.account.language')}</span>
        <select
          value={locale}
          onChange={(event) => setLocale(event.target.value as SupportedLocale)}
        >
          <option value="pt-BR">{t('common.account.portuguese')}</option>
          <option value="en">{t('common.account.english')}</option>
        </select>
      </label>
      <label className="preference-field">
        <span>{t('common.account.theme')}</span>
        <select
          value={theme}
          onChange={(event) => setTheme(event.target.value as ThemePreference)}
        >
          <option value="system">{t('common.account.system')}</option>
          <option value="light">{t('common.account.light')}</option>
          <option value="dark">{t('common.account.dark')}</option>
        </select>
      </label>
    </div>
  )
}
