import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { User } from '../api/auth'

type AppShellProps = {
  children: ReactNode
  user: User
  isLoggingOut: boolean
  logoutError: string | null
  onLogout: () => void
  isPlatformAdmin?: boolean
  activePage?: 'home' | 'admin'
  organizationName?: string
}

export function AppShell({
  children,
  user,
  isLoggingOut,
  logoutError,
  onLogout,
  isPlatformAdmin = false,
  activePage = 'home',
  organizationName,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="product-mark" to="/app" aria-label="Auron home">
          <span className="product-symbol" aria-hidden="true">A</span>
          <span>Auron</span>
        </Link>

        <div className="account-area">
          <div className="account-copy">
            <strong>{user.name}</strong>
            <span>{user.email}</span>
          </div>
          <button
            className="button button-secondary"
            type="button"
            onClick={onLogout}
            disabled={isLoggingOut}
          >
            {isLoggingOut ? 'Signing out…' : 'Log out'}
          </button>
        </div>
      </header>

      <div className="app-layout">
        <aside className="app-sidebar" aria-label="Primary navigation">
          <nav>
            <Link
              className={`nav-item${activePage === 'home' ? ' nav-item-active' : ''}`}
              to="/app"
              aria-current={activePage === 'home' ? 'page' : undefined}
            >
              Home
            </Link>
            {isPlatformAdmin ? (
              <Link
                className={`nav-item${activePage === 'admin' ? ' nav-item-active' : ''}`}
                to="/admin"
                aria-current={activePage === 'admin' ? 'page' : undefined}
              >
                Admin
              </Link>
            ) : null}
          </nav>
          {organizationName ? (
            <div className="sidebar-organization">
              <span>Organization</span>
              <strong>{organizationName}</strong>
              <Link to="/app">Switch organization</Link>
            </div>
          ) : (
            <p className="sidebar-note">Organization access is selected separately from authentication.</p>
          )}
        </aside>

        <main className="app-content">
          {logoutError ? <p className="inline-error" role="alert">{logoutError}</p> : null}
          {children}
        </main>
      </div>
    </div>
  )
}
