import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { User } from '../api/auth'
import { BrandLogo } from './BrandLogo'
import { PreferenceControls } from './PreferenceControls'

type AppShellProps = {
  children: ReactNode
  user: User
  isLoggingOut: boolean
  logoutError: string | null
  onLogout: () => void
  isPlatformAdmin?: boolean
  activePage?: 'overview' | 'admin' | 'account' | 'competitiveIntelligence' | 'applicationLogs'
  organizationName?: string
  competitiveIntelligencePath?: string
  applicationLogsPath?: string
}

type NavigationProps = {
  activePage: 'overview' | 'admin' | 'account' | 'competitiveIntelligence' | 'applicationLogs'
  isPlatformAdmin: boolean
  competitiveIntelligencePath?: string
  applicationLogsPath?: string
  onNavigate?: () => void
}

function Navigation({
  activePage,
  isPlatformAdmin,
  competitiveIntelligencePath,
  applicationLogsPath,
  onNavigate,
}: NavigationProps) {
  const { t } = useTranslation()

  return (
    <nav className="app-navigation" aria-label={t('common.navigation.primary')}>
      <Link
        className={`nav-item${activePage === 'overview' ? ' nav-item-active' : ''}`}
        to="/app"
        aria-current={activePage === 'overview' ? 'page' : undefined}
        onClick={onNavigate}
      >
        <span className="nav-icon" aria-hidden="true">⌂</span>
        <span>{t('common.navigation.overview')}</span>
      </Link>
      {competitiveIntelligencePath ? (
        <Link
          className={`nav-item${activePage === 'competitiveIntelligence' ? ' nav-item-active' : ''}`}
          to={competitiveIntelligencePath}
          aria-current={activePage === 'competitiveIntelligence' ? 'page' : undefined}
          onClick={onNavigate}
        >
          <span className="nav-icon" aria-hidden="true">◇</span>
          <span>{t('modules.competitive_intelligence.name')}</span>
        </Link>
      ) : null}
      {applicationLogsPath ? (
        <Link
          className={`nav-item${activePage === 'applicationLogs' ? ' nav-item-active' : ''}`}
          to={applicationLogsPath}
          aria-current={activePage === 'applicationLogs' ? 'page' : undefined}
          onClick={onNavigate}
        >
          <span className="nav-icon" aria-hidden="true">≡</span>
          <span>{t('applicationLogs.navigation')}</span>
        </Link>
      ) : null}
      {isPlatformAdmin ? (
        <Link
          className={`nav-item${activePage === 'admin' ? ' nav-item-active' : ''}`}
          to="/admin"
          aria-current={activePage === 'admin' ? 'page' : undefined}
          onClick={onNavigate}
        >
          <span className="nav-icon" aria-hidden="true">◇</span>
          <span>{t('common.navigation.admin')}</span>
        </Link>
      ) : null}
    </nav>
  )
}

export function AppShell({
  children,
  user,
  isLoggingOut,
  logoutError,
  onLogout,
  isPlatformAdmin = false,
  activePage = 'overview',
  organizationName,
  competitiveIntelligencePath,
  applicationLogsPath,
}: AppShellProps) {
  const { t } = useTranslation()
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const drawerRef = useRef<HTMLElement>(null)
  const drawerTriggerRef = useRef<HTMLButtonElement>(null)
  const userMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!isDrawerOpen) return
    const drawer = drawerRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    drawer?.querySelector<HTMLElement>('button')?.focus()

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsDrawerOpen(false)
        drawerTriggerRef.current?.focus()
        return
      }
      if (event.key !== 'Tab' || !drawer) return

      const focusable = Array.from(
        drawer.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isDrawerOpen])

  useEffect(() => {
    if (!isUserMenuOpen) return

    function handlePointerDown(event: PointerEvent) {
      if (!userMenuRef.current?.contains(event.target as Node)) setIsUserMenuOpen(false)
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsUserMenuOpen(false)
        userMenuRef.current?.querySelector<HTMLElement>('button')?.focus()
      }
    }

    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isUserMenuOpen])

  const closeDrawer = () => setIsDrawerOpen(false)
  const accountContext = activePage === 'account'
    ? t('common.navigation.account')
    : activePage === 'competitiveIntelligence'
      ? t('modules.competitive_intelligence.name')
      : activePage === 'applicationLogs'
        ? t('applicationLogs.navigation')
      : t(activePage === 'admin' ? 'common.navigation.admin' : 'common.navigation.overview')

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">{t('common.navigation.skip')}</a>

      <aside className="desktop-sidebar">
        <Link className="sidebar-brand" to="/app" aria-label={t('common.navigation.auronHome')}>
          <BrandLogo variant="horizontal" eager />
        </Link>
        <Navigation
          activePage={activePage}
          isPlatformAdmin={isPlatformAdmin}
          competitiveIntelligencePath={competitiveIntelligencePath}
          applicationLogsPath={applicationLogsPath}
        />
        <div className="sidebar-context">
          {organizationName ? (
            <div className="organization-context">
              <span>{t('common.organization.label')}</span>
              <strong>{organizationName}</strong>
              <Link to="/app">{t('common.organization.switch')}</Link>
            </div>
          ) : (
            <p>{t('common.organization.separateContext')}</p>
          )}
        </div>
      </aside>

      <div className="app-frame">
        <header className="app-topbar">
          <div className="mobile-brand-area">
            <button
              ref={drawerTriggerRef}
              className="icon-button mobile-menu-button"
              type="button"
              aria-label={t('common.navigation.openMenu')}
              aria-expanded={isDrawerOpen}
              aria-controls="mobile-navigation"
              onClick={() => setIsDrawerOpen(true)}
            >
              <span aria-hidden="true">☰</span>
            </button>
            <Link to="/app" aria-label={t('common.navigation.auronHome')}>
              <BrandLogo variant="mark" eager />
            </Link>
          </div>

          <div className="topbar-context">
            <span>{organizationName ? t('common.organization.label') : 'Auron'}</span>
            <strong>
              {organizationName ?? accountContext}
            </strong>
          </div>

          <div className="user-menu" ref={userMenuRef}>
            <button
              className="user-menu-trigger"
              type="button"
              aria-label={t('common.account.menu', { name: user.name })}
              aria-expanded={isUserMenuOpen}
              aria-haspopup="dialog"
              aria-controls="user-preferences"
              onClick={() => setIsUserMenuOpen((open) => !open)}
            >
              <span className="user-avatar" aria-hidden="true">{user.name.trim().charAt(0).toUpperCase()}</span>
              <span className="user-summary">
                <strong>{user.name}</strong>
                <small>{user.email}</small>
              </span>
              <span aria-hidden="true">⌄</span>
            </button>
            {isUserMenuOpen ? (
              <div
                className="user-menu-panel"
                id="user-preferences"
                role="dialog"
                aria-label={t('common.account.preferences')}
              >
                <div className="user-menu-links">
                  <Link to="/app/settings/profile" onClick={() => setIsUserMenuOpen(false)}>
                    {t('common.account.myAccount')}
                  </Link>
                  {isPlatformAdmin ? (
                    <Link to="/admin" onClick={() => setIsUserMenuOpen(false)}>
                      {t('common.navigation.admin')}
                    </Link>
                  ) : null}
                </div>
                <p className="menu-heading">{t('common.account.preferences')}</p>
                <PreferenceControls />
                <button
                  className="button button-secondary button-full"
                  type="button"
                  onClick={onLogout}
                  disabled={isLoggingOut}
                >
                  {isLoggingOut ? t('common.account.loggingOut') : t('common.account.logout')}
                </button>
              </div>
            ) : null}
          </div>
        </header>

        <main className="app-content" id="main-content" tabIndex={-1}>
          {logoutError ? <div className="alert alert-danger" role="alert">{logoutError}</div> : null}
          {children}
        </main>
      </div>

      {isDrawerOpen ? (
        <div className="mobile-drawer-layer">
          <button
            className="drawer-overlay"
            type="button"
            aria-label={t('common.navigation.closeOverlay')}
            onClick={() => {
              closeDrawer()
              drawerTriggerRef.current?.focus()
            }}
          />
          <aside
            className="mobile-drawer"
            id="mobile-navigation"
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label={t('common.navigation.primary')}
          >
            <div className="drawer-header">
              <BrandLogo variant="horizontal" eager />
              <button
                className="icon-button"
                type="button"
                aria-label={t('common.navigation.closeMenu')}
                onClick={() => {
                  closeDrawer()
                  drawerTriggerRef.current?.focus()
                }}
              >
                <span aria-hidden="true">×</span>
              </button>
            </div>
            <Navigation
              activePage={activePage}
              isPlatformAdmin={isPlatformAdmin}
              competitiveIntelligencePath={competitiveIntelligencePath}
              applicationLogsPath={applicationLogsPath}
              onNavigate={closeDrawer}
            />
            {organizationName ? (
              <div className="organization-context">
                <span>{t('common.organization.label')}</span>
                <strong>{organizationName}</strong>
                <Link to="/app" onClick={closeDrawer}>{t('common.organization.switch')}</Link>
              </div>
            ) : null}
            <div className="drawer-account">
              <div className="drawer-user">
                <strong>{user.name}</strong>
                <span>{user.email}</span>
              </div>
              <div className="drawer-account-links">
                <Link to="/app/settings/profile" onClick={closeDrawer}>
                  {t('common.account.myAccount')}
                </Link>
                {isPlatformAdmin ? (
                  <Link to="/admin" onClick={closeDrawer}>{t('common.navigation.admin')}</Link>
                ) : null}
              </div>
              <PreferenceControls />
              <button
                className="button button-secondary button-full"
                type="button"
                onClick={onLogout}
                disabled={isLoggingOut}
              >
                {isLoggingOut ? t('common.account.loggingOut') : t('common.account.logout')}
              </button>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  )
}
