import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { getPlatformAdminStatus } from '../../api/platform-admin'
import { useAuth } from '../../auth/useAuth'
import { AppShell } from '../AppShell'

type AccountSettingsLayoutProps = {
  activePage: 'profile' | 'security'
  children: ReactNode
}

export function AccountSettingsLayout({
  activePage,
  children,
}: AccountSettingsLayoutProps) {
  const { t } = useTranslation()
  const { user, logout } = useAuth()
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void getPlatformAdminStatus()
      .then((hasAccess) => { if (active) setIsPlatformAdmin(hasAccess) })
      .catch(() => { if (active) setIsPlatformAdmin(false) })
    return () => { active = false }
  }, [])

  if (user === null) return null

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
    } catch {
      setLogoutError(t('common.account.logoutError'))
      setIsLoggingOut(false)
    }
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin={isPlatformAdmin}
      activePage="account"
    >
      <header className="page-header settings-page-header">
        <p className="eyebrow">{t('accountSettings.eyebrow')}</p>
        <h1>{t('accountSettings.title')}</h1>
        <p>{t('accountSettings.description')}</p>
      </header>
      <div className="settings-layout">
        <nav className="settings-navigation" aria-label={t('accountSettings.navigation')}>
          <Link
            to="/app/settings/profile"
            className={activePage === 'profile' ? 'settings-nav-active' : undefined}
            aria-current={activePage === 'profile' ? 'page' : undefined}
          >
            {t('accountSettings.profile.navigation')}
          </Link>
          <Link
            to="/app/settings/security"
            className={activePage === 'security' ? 'settings-nav-active' : undefined}
            aria-current={activePage === 'security' ? 'page' : undefined}
          >
            {t('accountSettings.security.navigation')}
          </Link>
        </nav>
        <div className="settings-content">{children}</div>
      </div>
    </AppShell>
  )
}
