import { useState } from 'react'
import { Navigate } from 'react-router-dom'

import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'
import { useAuth } from '../auth/useAuth'

export function LoginPage() {
  const { status, refreshUser, loginWithGoogle } = useAuth()
  const [isRedirecting, setIsRedirecting] = useState(false)

  if (status === 'loading') {
    return <AuthenticationLoading />
  }
  if (status === 'error') {
    return <AuthenticationError onRetry={refreshUser} />
  }
  if (status === 'authenticated') {
    return <Navigate to="/app" replace />
  }

  function handleGoogleLogin() {
    setIsRedirecting(true)
    loginWithGoogle()
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-heading">
        <div className="login-introduction">
          <div className="product-mark product-mark-light">
            <span className="product-symbol" aria-hidden="true">A</span>
            <span>Auron</span>
          </div>
          <div>
            <p className="eyebrow eyebrow-light">Secure workspace access</p>
            <h1 id="login-heading">A clear foundation for the work ahead.</h1>
            <p>Sign in to access your account and continue to Auron.</p>
          </div>
        </div>

        <div className="login-action">
          <div>
            <p className="eyebrow">Welcome back</p>
            <h2>Sign in to continue</h2>
            <p>Use your Google account to authenticate securely.</p>
          </div>

          <button
            className="button google-button"
            type="button"
            onClick={handleGoogleLogin}
            disabled={isRedirecting}
          >
            {isRedirecting ? 'Redirecting…' : 'Continue with Google'}
          </button>

          <p className="security-note">Authentication is completed by the backend. No provider token is stored in this browser application.</p>
        </div>
      </section>
    </main>
  )
}
