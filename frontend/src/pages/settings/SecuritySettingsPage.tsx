import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import {
  AccountApiError,
  changePassword,
  getAccountSettings,
  startPasswordEnrollment,
  type AccountSettings,
} from '../../api/account'
import { useAuth } from '../../auth/useAuth'
import { LoadingState } from '../../components/LoadingState'
import { AccountSettingsLayout } from '../../components/settings/AccountSettingsLayout'
import { usePageMetadata } from '../../hooks/usePageMetadata'

type PageStatus = 'loading' | 'ready' | 'error'

export function SecuritySettingsPage() {
  const { t } = useTranslation()
  const { user, refreshUser } = useAuth()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [account, setAccount] = useState<AccountSettings | null>(null)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [isChangingPassword, setIsChangingPassword] = useState(false)
  const [isStartingEnrollment, setIsStartingEnrollment] = useState(false)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null)
  const [enrollmentStarted, setEnrollmentStarted] = useState(false)
  usePageMetadata(t('accountSettings.meta.securityTitle'), t('accountSettings.meta.securityDescription'))

  const loadAccount = useCallback(async () => {
    setPageStatus('loading')
    try {
      setAccount(await getAccountSettings())
      setPageStatus('ready')
    } catch (error) {
      if (error instanceof AccountApiError && error.status === 401) {
        await refreshUser()
        return
      }
      setPageStatus('error')
    }
  }, [refreshUser])

  useEffect(() => { void loadAccount() }, [loadAccount])

  if (user === null) return null

  function validatePasswordChange(): string | null {
    if (!currentPassword) return t('accountSettings.security.currentPasswordRequired')
    if (newPassword.length < 10) return t('accountSettings.security.passwordMinimum')
    if (newPassword.length > 256) return t('accountSettings.security.passwordMaximum')
    if (newPassword !== confirmPassword) return t('accountSettings.security.passwordMismatch')
    if (newPassword === currentPassword) return t('accountSettings.security.passwordReuse')
    return null
  }

  async function handlePasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPasswordError(null)
    setPasswordSuccess(null)
    const validationError = validatePasswordChange()
    if (validationError !== null) {
      setPasswordError(validationError)
      return
    }

    setIsChangingPassword(true)
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setPasswordSuccess(t('accountSettings.security.passwordChanged'))
    } catch (error) {
      if (error instanceof AccountApiError && error.status === 401) {
        await refreshUser()
      } else if (error instanceof AccountApiError && error.detail === 'Current password is incorrect.') {
        setPasswordError(t('accountSettings.security.currentPasswordIncorrect'))
      } else if (error instanceof AccountApiError && error.detail === 'New password must be different from the current password.') {
        setPasswordError(t('accountSettings.security.passwordReuse'))
      } else if (error instanceof AccountApiError && error.status === 422) {
        setPasswordError(t('accountSettings.security.passwordPolicy'))
      } else {
        setPasswordError(t('accountSettings.security.passwordChangeError'))
      }
    } finally {
      setIsChangingPassword(false)
    }
  }

  async function handleEnrollmentStart() {
    setPasswordError(null)
    setIsStartingEnrollment(true)
    try {
      await startPasswordEnrollment()
      setEnrollmentStarted(true)
    } catch (error) {
      if (error instanceof AccountApiError && error.status === 401) {
        await refreshUser()
      } else if (error instanceof AccountApiError && error.status === 403) {
        setPasswordError(t('accountSettings.security.enrollmentRequiresVerified'))
      } else if (error instanceof AccountApiError && error.status === 409) {
        await loadAccount()
      } else {
        setPasswordError(t('accountSettings.security.enrollmentError'))
      }
    } finally {
      setIsStartingEnrollment(false)
    }
  }

  if (pageStatus === 'loading') {
    return (
      <AccountSettingsLayout activePage="security">
        <LoadingState label={t('common.status.loadingContent')} />
      </AccountSettingsLayout>
    )
  }

  if (pageStatus === 'error' || account === null) {
    return (
      <AccountSettingsLayout activePage="security">
        <section className="settings-section settings-error" role="alert">
          <h2>{t('accountSettings.security.loadErrorTitle')}</h2>
          <p>{t('accountSettings.security.loadErrorBody')}</p>
          <button className="button button-primary" type="button" onClick={() => void loadAccount()}>
            {t('common.actions.retry')}
          </button>
        </section>
      </AccountSettingsLayout>
    )
  }

  return (
    <AccountSettingsLayout activePage="security">
      <section className="settings-section" aria-labelledby="security-settings-title">
        <div className="settings-section-heading">
          <h2 id="security-settings-title">{t('accountSettings.security.title')}</h2>
          <p>{t('accountSettings.security.description')}</p>
        </div>

        <div className="authentication-methods" aria-labelledby="authentication-methods-title">
          <h3 className="authentication-methods-title" id="authentication-methods-title">
            {t('accountSettings.security.methodsTitle')}
          </h3>
          <div className="authentication-method">
            <div><strong>{t('accountSettings.security.google')}</strong><span>{t('accountSettings.security.googleDescription')}</span></div>
            <span className={`badge ${account.authentication_methods.google ? 'badge-success' : 'badge-info'}`}>
              {t(account.authentication_methods.google
                ? 'accountSettings.security.connected'
                : 'accountSettings.security.notConnected')}
            </span>
          </div>
          <div className="authentication-method">
            <div><strong>{t('accountSettings.security.password')}</strong><span>{t('accountSettings.security.passwordDescription')}</span></div>
            <span className={`badge ${account.authentication_methods.password ? 'badge-success' : 'badge-info'}`}>
              {t(account.authentication_methods.password
                ? 'accountSettings.security.configured'
                : 'accountSettings.security.notConfigured')}
            </span>
          </div>
        </div>

        {account.authentication_methods.password ? (
          <div className="password-settings">
            <div className="settings-section-heading">
              <h3>{t('accountSettings.security.changePasswordTitle')}</h3>
              <p>{t('accountSettings.security.changePasswordDescription')}</p>
            </div>
            <form className="settings-form" onSubmit={(event) => void handlePasswordChange(event)} noValidate>
              <label className="field-label" htmlFor="current-password">{t('accountSettings.security.currentPassword')}</label>
              <input className="text-input" id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required disabled={isChangingPassword} />
              <label className="field-label" htmlFor="new-password">{t('accountSettings.security.newPassword')}</label>
              <input className="text-input" id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} minLength={10} maxLength={256} required disabled={isChangingPassword} aria-describedby="password-policy" />
              <p className="field-help" id="password-policy">{t('accountSettings.security.passwordPolicy')}</p>
              <label className="field-label" htmlFor="confirm-password">{t('accountSettings.security.confirmPassword')}</label>
              <input className="text-input" id="confirm-password" type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} minLength={10} maxLength={256} required disabled={isChangingPassword} />
              {passwordError ? <div className="alert alert-danger" role="alert">{passwordError}</div> : null}
              {passwordSuccess ? <div className="alert alert-info" role="status">{passwordSuccess}</div> : null}
              <button className="button button-primary settings-submit" type="submit" disabled={isChangingPassword}>
                {isChangingPassword ? t('accountSettings.security.changingPassword') : t('accountSettings.security.changePassword')}
              </button>
            </form>
          </div>
        ) : (
          <div className="password-settings">
            <div className="settings-section-heading">
              <h3>{t('accountSettings.security.addPasswordTitle')}</h3>
              <p>{t('accountSettings.security.addPasswordDescription')}</p>
            </div>
            {enrollmentStarted ? (
              <div className="alert alert-info" role="status">
                <strong>{t('accountSettings.security.enrollmentSentTitle')}</strong>
                <span>{t('accountSettings.security.enrollmentSentBody', { email: account.user.email })}</span>
              </div>
            ) : (
              <button className="button button-primary" type="button" onClick={() => void handleEnrollmentStart()} disabled={isStartingEnrollment || !account.user.email_verified_at}>
                {isStartingEnrollment ? t('accountSettings.security.sendingEnrollment') : t('accountSettings.security.sendEnrollment')}
              </button>
            )}
            {!account.user.email_verified_at ? <p className="field-help">{t('accountSettings.security.enrollmentRequiresVerified')}</p> : null}
            {passwordError ? <div className="alert alert-danger" role="alert">{passwordError}</div> : null}
          </div>
        )}
      </section>
    </AccountSettingsLayout>
  )
}
