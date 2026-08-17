import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { AuthApiError, completeEmailVerification, resendEmailVerification } from '../api/auth'
import { useAuth } from '../auth/useAuth'
import { StatusPage } from '../components/StatusPage'
import { usePageMetadata } from '../hooks/usePageMetadata'

type VerificationStatus = 'form' | 'invalid' | 'expired' | 'completed' | 'error'

function readVerificationToken(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get('token')
}

export function VerifyEmailPage() {
  const { t } = useTranslation()
  const { refreshUser } = useAuth()
  const navigate = useNavigate()
  const [token, setToken] = useState(readVerificationToken)
  const [password, setPassword] = useState('')
  const [passwordConfirmation, setPasswordConfirmation] = useState('')
  const [status, setStatus] = useState<VerificationStatus>(token ? 'form' : 'invalid')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [resendEmail, setResendEmail] = useState('')
  const [resendMessage, setResendMessage] = useState<string | null>(null)
  usePageMetadata(t('auth.meta.verifyTitle'), t('auth.meta.verifyDescription'))

  useEffect(() => {
    function consumeFragmentToken() {
      const nextToken = readVerificationToken()
      if (!nextToken) return
      setToken(nextToken)
      setStatus('form')
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    }

    consumeFragmentToken()
    window.addEventListener('hashchange', consumeFragmentToken)
    return () => window.removeEventListener('hashchange', consumeFragmentToken)
  }, [])

  async function handleCompletion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    if (password.length < 10) {
      setFormError(t('auth.verify.minimum'))
      return
    }
    if (password !== passwordConfirmation) {
      setFormError(t('auth.verify.mismatch'))
      return
    }
    setIsSubmitting(true)
    setFormError(null)
    try {
      await completeEmailVerification(token, password)
      await refreshUser()
      navigate('/app', { replace: true })
    } catch (error) {
      if (error instanceof AuthApiError && error.status === 410) setStatus('expired')
      else if (error instanceof AuthApiError && error.status === 409) setStatus('completed')
      else if (error instanceof AuthApiError && error.status === 400) setStatus('invalid')
      else setStatus('error')
      setIsSubmitting(false)
    }
  }

  async function handleResend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setResendMessage(null)
    try {
      await resendEmailVerification(resendEmail)
      setResendMessage(t('auth.verify.resendSuccess'))
    } catch {
      setResendMessage(t('auth.verify.resendError'))
    }
  }

  if (status !== 'form') {
    const copy = status === 'expired'
      ? [t('auth.verify.expiredTitle'), t('auth.verify.expiredBody')]
      : status === 'completed'
        ? [t('auth.verify.completedTitle'), t('auth.verify.completedBody')]
        : status === 'invalid'
          ? [t('auth.verify.invalidTitle'), t('auth.verify.invalidBody')]
          : [t('auth.verify.errorTitle'), t('auth.verify.errorBody')]

    return (
      <StatusPage>
        <section className="status-card">
          <p className="eyebrow">{t('auth.verify.eyebrow')}</p>
          <h1>{copy[0]}</h1>
          <p>{copy[1]}</p>
          {status === 'expired' ? (
            <form className="auth-form resend-form" onSubmit={(event) => void handleResend(event)}>
              <label className="field-label" htmlFor="resend-email">{t('auth.verify.email')}</label>
              <input id="resend-email" className="text-input" type="email" autoComplete="email" value={resendEmail} onChange={(event) => setResendEmail(event.target.value)} required />
              <button className="button button-primary" type="submit">{t('auth.verify.resend')}</button>
              {resendMessage ? <p className="alert alert-info" role="status">{resendMessage}</p> : null}
            </form>
          ) : status === 'error' ? (
            <button className="button button-primary" type="button" onClick={() => setStatus('form')}>
              {t('common.actions.retry')}
            </button>
          ) : (
            <Link className="button button-primary status-link" to="/login">{t('auth.verify.return')}</Link>
          )}
        </section>
      </StatusPage>
    )
  }

  return (
    <StatusPage>
      <section className="status-card">
        <p className="eyebrow">{t('auth.verify.setupEyebrow')}</p>
        <h1>{t('auth.verify.createPassword')}</h1>
        <p>{t('auth.verify.passwordHint')}</p>
        <form className="auth-form" onSubmit={(event) => void handleCompletion(event)}>
          <label className="field-label" htmlFor="new-password">{t('auth.verify.password')}</label>
          <input id="new-password" className="text-input" type="password" autoComplete="new-password" minLength={10} maxLength={256} value={password} aria-invalid={formError ? true : undefined} aria-describedby={formError ? 'verification-error' : undefined} onChange={(event) => setPassword(event.target.value)} required />
          <label className="field-label" htmlFor="confirm-password">{t('auth.verify.confirmation')}</label>
          <input id="confirm-password" className="text-input" type="password" autoComplete="new-password" minLength={10} maxLength={256} value={passwordConfirmation} aria-invalid={formError ? true : undefined} aria-describedby={formError ? 'verification-error' : undefined} onChange={(event) => setPasswordConfirmation(event.target.value)} required />
          {formError ? <div className="alert alert-danger" id="verification-error" role="alert">{formError}</div> : null}
          <button className="button button-primary" type="submit" disabled={isSubmitting}>
            {isSubmitting ? t('auth.verify.finishing') : t('auth.verify.finish')}
          </button>
        </form>
      </section>
    </StatusPage>
  )
}
