import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { AuthApiError, loginWithPassword } from '../api/auth'
import { useAuth } from '../auth/useAuth'
import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'

export function LoginPage() {
  const { status, refreshUser, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRedirecting, setIsRedirecting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  if (status === 'loading') return <AuthenticationLoading />
  if (status === 'error') return <AuthenticationError onRetry={refreshUser} />
  if (status === 'authenticated') return <Navigate to="/app" replace />

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSubmitting(true)
    setFormError(null)
    try {
      await loginWithPassword(email, password)
      await refreshUser()
      navigate('/app', { replace: true })
    } catch (error) {
      setFormError(
        error instanceof AuthApiError && error.status === 401
          ? 'Invalid email or password.'
          : 'We could not sign you in. Check the server and try again.',
      )
      setIsSubmitting(false)
    }
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
          </div>

          <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
            <label className="field-label" htmlFor="login-email">Email</label>
            <input
              id="login-email"
              className="text-input"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
            />
            <label className="field-label" htmlFor="login-password">Password</label>
            <input
              id="login-password"
              className="text-input"
              type="password"
              autoComplete="current-password"
              maxLength={256}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
            {formError ? <p className="inline-error" role="alert">{formError}</p> : null}
            <button className="button button-primary" type="submit" disabled={isSubmitting || isRedirecting}>
              {isSubmitting ? 'Signing in...' : 'Sign in'}
            </button>
          </form>

          <div className="auth-divider"><span>or</span></div>
          <button
            className="button google-button"
            type="button"
            onClick={handleGoogleLogin}
            disabled={isRedirecting || isSubmitting}
          >
            {isRedirecting ? 'Redirecting...' : 'Continue with Google'}
          </button>
          <p className="auth-switch">Don't have an account? <Link to="/register">Create account</Link></p>
          <p className="security-note">Authentication is completed by the backend. No password or token is stored by this browser application.</p>
        </div>
      </section>
    </main>
  )
}
