import { useState, type FormEvent } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { AuthApiError, registerLocalAccount } from '../api/auth'
import { useAuth } from '../auth/useAuth'
import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'

export function RegisterPage() {
  const { status, refreshUser, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
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
      await registerLocalAccount(name, email)
      navigate('/check-email', { replace: true })
    } catch (error) {
      setFormError(
        error instanceof AuthApiError && error.status === 422
          ? 'Enter a valid name and email address.'
          : 'We could not send verification instructions. Please try again.',
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
      <section className="login-card" aria-labelledby="register-heading">
        <div className="login-introduction">
          <div className="product-mark product-mark-light">
            <span className="product-symbol" aria-hidden="true">A</span>
            <span>Auron</span>
          </div>
          <div>
            <p className="eyebrow eyebrow-light">Create your account</p>
            <h1 id="register-heading">Start with one global Auron identity.</h1>
            <p>Your Organization access remains separate and will appear after sign-in.</p>
          </div>
        </div>

        <div className="login-action">
          <div>
            <p className="eyebrow">Get started</p>
            <h2>Create your Auron account</h2>
            <p>We'll verify your email before you choose a password.</p>
          </div>
          <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
            <label className="field-label" htmlFor="register-name">Name</label>
            <input id="register-name" className="text-input" autoComplete="name" maxLength={255} value={name} onChange={(event) => setName(event.target.value)} required />
            <label className="field-label" htmlFor="register-email">Email</label>
            <input id="register-email" className="text-input" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            {formError ? <p className="inline-error" role="alert">{formError}</p> : null}
            <button className="button button-primary" type="submit" disabled={isSubmitting || isRedirecting}>
              {isSubmitting ? 'Sending...' : 'Continue'}
            </button>
          </form>
          <div className="auth-divider"><span>or</span></div>
          <button className="button google-button" type="button" onClick={handleGoogleLogin} disabled={isRedirecting || isSubmitting}>
            {isRedirecting ? 'Redirecting...' : 'Continue with Google'}
          </button>
          <p className="auth-switch">Already have an account? <Link to="/login">Sign in</Link></p>
        </div>
      </section>
    </main>
  )
}
