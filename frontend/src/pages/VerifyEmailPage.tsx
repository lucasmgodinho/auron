import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import {
  AuthApiError,
  completeEmailVerification,
  resendEmailVerification,
} from '../api/auth'
import { useAuth } from '../auth/useAuth'

type VerificationStatus = 'form' | 'invalid' | 'expired' | 'completed' | 'error'

function readVerificationToken(): string | null {
  return new URLSearchParams(window.location.hash.slice(1)).get('token')
}

export function VerifyEmailPage() {
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

  useEffect(() => {
    function consumeFragmentToken() {
      const nextToken = readVerificationToken()
      if (!nextToken) return
      setToken(nextToken)
      setStatus('form')
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}`,
      )
    }

    consumeFragmentToken()
    window.addEventListener('hashchange', consumeFragmentToken)
    return () => window.removeEventListener('hashchange', consumeFragmentToken)
  }, [])

  async function handleCompletion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token) return
    if (password.length < 10) {
      setFormError('Use at least 10 characters.')
      return
    }
    if (password !== passwordConfirmation) {
      setFormError('Passwords do not match.')
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
      setResendMessage('If this email can be used to continue, new instructions have been sent.')
    } catch {
      setResendMessage('We could not send verification instructions. Please try again.')
    }
  }

  if (status !== 'form') {
    const copy = status === 'expired'
      ? ['Link expired', 'This verification link has expired.']
      : status === 'completed'
        ? ['Setup unavailable', 'This setup can no longer be completed. Sign in if your account is ready.']
        : status === 'invalid'
          ? ['Invalid link', 'This verification link is invalid.']
          : ['Verification unavailable', 'We could not finish account setup. Please try again.']
    return (
      <main className="status-page">
        <section className="status-card">
          <p className="eyebrow">Email verification</p>
          <h1>{copy[0]}</h1>
          <p>{copy[1]}</p>
          {status === 'expired' ? (
            <form className="auth-form resend-form" onSubmit={(event) => void handleResend(event)}>
              <label className="field-label" htmlFor="resend-email">Email</label>
              <input id="resend-email" className="text-input" type="email" value={resendEmail} onChange={(event) => setResendEmail(event.target.value)} required />
              <button className="button button-primary" type="submit">Resend verification email</button>
              {resendMessage ? <p role="status">{resendMessage}</p> : null}
            </form>
          ) : status === 'error' ? (
            <button className="button button-primary" type="button" onClick={() => setStatus('form')}>
              Try again
            </button>
          ) : (
            <Link className="button button-primary status-link" to="/login">Return to sign in</Link>
          )}
        </section>
      </main>
    )
  }

  return (
    <main className="status-page">
      <section className="status-card">
        <p className="eyebrow">Email verified setup</p>
        <h1>Create your password</h1>
        <p>Use at least 10 characters. Spaces and passphrases are allowed.</p>
        <form className="auth-form" onSubmit={(event) => void handleCompletion(event)}>
          <label className="field-label" htmlFor="new-password">Create password</label>
          <input id="new-password" className="text-input" type="password" autoComplete="new-password" minLength={10} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
          <label className="field-label" htmlFor="confirm-password">Confirm password</label>
          <input id="confirm-password" className="text-input" type="password" autoComplete="new-password" minLength={10} maxLength={256} value={passwordConfirmation} onChange={(event) => setPasswordConfirmation(event.target.value)} required />
          {formError ? <p className="inline-error" role="alert">{formError}</p> : null}
          <button className="button button-primary" type="submit" disabled={isSubmitting}>
            {isSubmitting ? 'Finishing setup...' : 'Finish account setup'}
          </button>
        </form>
      </section>
    </main>
  )
}
