import { useState } from 'react'

import { useAuth } from '../auth/useAuth'
import { AppShell } from '../components/AppShell'

export function AppPage() {
  const { user, logout } = useAuth()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  if (user === null) {
    return null
  }

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
    } catch {
      setLogoutError('We couldn’t log you out. Please check the server and try again.')
      setIsLoggingOut(false)
    }
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
    >
      <section className="welcome-panel" aria-labelledby="welcome-heading">
        <p className="eyebrow">Account authenticated</p>
        <h1 id="welcome-heading">Welcome, {user.name}</h1>
        <p>Your account is authenticated successfully and the application foundation is ready.</p>
      </section>

      <section className="next-step-card" aria-labelledby="next-step-heading">
        <div className="next-step-icon" aria-hidden="true">01</div>
        <div>
          <h2 id="next-step-heading">What comes next</h2>
          <p>Organization selection will be added as a separate step. No tenant is selected by authentication.</p>
        </div>
      </section>
    </AppShell>
  )
}
