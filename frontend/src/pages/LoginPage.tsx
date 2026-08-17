import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { AuthApiError, loginWithPassword } from '../api/auth'
import { useAuth } from '../auth/useAuth'
import { AuthLayout } from '../components/AuthLayout'
import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'
import { usePageMetadata } from '../hooks/usePageMetadata'

export function LoginPage() {
  const { t } = useTranslation()
  const { status, refreshUser, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRedirecting, setIsRedirecting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  usePageMetadata(t('auth.meta.loginTitle'), t('auth.meta.loginDescription'))

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
          ? t('auth.login.invalid')
          : t('auth.login.unavailable'),
      )
      setIsSubmitting(false)
    }
  }

  function handleGoogleLogin() {
    setIsRedirecting(true)
    loginWithGoogle()
  }

  return (
    <AuthLayout labelledBy="login-heading">
      <div className="auth-form-heading">
        <p className="eyebrow">{t('auth.login.eyebrow')}</p>
        <h2 id="login-heading">{t('auth.login.title')}</h2>
      </div>
      <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="field-label" htmlFor="login-email">{t('auth.login.email')}</label>
        <input
          id="login-email"
          className="text-input"
          type="email"
          autoComplete="email"
          value={email}
          aria-invalid={formError ? true : undefined}
          aria-describedby={formError ? 'login-error' : undefined}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
        <label className="field-label" htmlFor="login-password">{t('auth.login.password')}</label>
        <input
          id="login-password"
          className="text-input"
          type="password"
          autoComplete="current-password"
          maxLength={256}
          value={password}
          aria-invalid={formError ? true : undefined}
          aria-describedby={formError ? 'login-error' : undefined}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
        {formError ? <div className="alert alert-danger" id="login-error" role="alert">{formError}</div> : null}
        <button className="button button-primary button-full" type="submit" disabled={isSubmitting || isRedirecting}>
          {isSubmitting ? t('auth.login.submitting') : t('auth.login.submit')}
        </button>
      </form>
      <div className="auth-divider"><span>{t('auth.login.separator')}</span></div>
      <button className="button google-button" type="button" onClick={handleGoogleLogin} disabled={isRedirecting || isSubmitting}>
        {isRedirecting ? t('auth.login.redirecting') : t('auth.login.google')}
      </button>
      <p className="auth-switch">{t('auth.login.noAccount')} <Link to="/register">{t('auth.login.createAccount')}</Link></p>
      <p className="security-note">{t('auth.login.security')}</p>
    </AuthLayout>
  )
}
