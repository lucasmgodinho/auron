import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { AuthApiError, registerLocalAccount } from '../api/auth'
import { useAuth } from '../auth/useAuth'
import { AuthLayout } from '../components/AuthLayout'
import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'
import { usePageMetadata } from '../hooks/usePageMetadata'

export function RegisterPage() {
  const { t } = useTranslation()
  const { status, refreshUser, loginWithGoogle } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isRedirecting, setIsRedirecting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  usePageMetadata(t('auth.meta.registerTitle'), t('auth.meta.registerDescription'))

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
          ? t('auth.register.invalid')
          : t('auth.register.unavailable'),
      )
      setIsSubmitting(false)
    }
  }

  function handleGoogleLogin() {
    setIsRedirecting(true)
    loginWithGoogle()
  }

  return (
    <AuthLayout
      labelledBy="register-heading"
      panelEyebrow={t('auth.register.panelEyebrow')}
      panelTitle={t('auth.register.panelTitle')}
      panelDescription={t('auth.register.panelDescription')}
    >
      <div className="auth-form-heading">
        <p className="eyebrow">{t('auth.register.eyebrow')}</p>
        <h2 id="register-heading">{t('auth.register.title')}</h2>
        <p>{t('auth.register.description')}</p>
      </div>
      <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
        <label className="field-label" htmlFor="register-name">{t('auth.register.name')}</label>
        <input id="register-name" className="text-input" autoComplete="name" maxLength={255} value={name} aria-invalid={formError ? true : undefined} aria-describedby={formError ? 'register-error' : undefined} onChange={(event) => setName(event.target.value)} required />
        <label className="field-label" htmlFor="register-email">{t('auth.register.email')}</label>
        <input id="register-email" className="text-input" type="email" autoComplete="email" value={email} aria-invalid={formError ? true : undefined} aria-describedby={formError ? 'register-error' : undefined} onChange={(event) => setEmail(event.target.value)} required />
        {formError ? <div className="alert alert-danger" id="register-error" role="alert">{formError}</div> : null}
        <button className="button button-primary button-full" type="submit" disabled={isSubmitting || isRedirecting}>
          {isSubmitting ? t('auth.register.submitting') : t('auth.register.submit')}
        </button>
      </form>
      <div className="auth-divider"><span>{t('auth.login.separator')}</span></div>
      <button className="button google-button" type="button" onClick={handleGoogleLogin} disabled={isRedirecting || isSubmitting}>
        {isRedirecting ? t('auth.register.redirecting') : t('auth.register.google')}
      </button>
      <p className="auth-switch">{t('auth.register.hasAccount')} <Link to="/login">{t('auth.register.signIn')}</Link></p>
    </AuthLayout>
  )
}
