import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { AccountApiError, updateProfile } from '../../api/account'
import { useAuth } from '../../auth/useAuth'
import { AccountSettingsLayout } from '../../components/settings/AccountSettingsLayout'
import { usePageMetadata } from '../../hooks/usePageMetadata'

export function ProfileSettingsPage() {
  const { t } = useTranslation()
  const { user, refreshUser } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [isSaving, setIsSaving] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  usePageMetadata(t('accountSettings.meta.profileTitle'), t('accountSettings.meta.profileDescription'))

  useEffect(() => {
    if (user !== null) setName(user.name)
  }, [user])

  if (user === null) return null
  const currentUser = user

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedName = name.trim()
    setFormError(null)
    setSuccessMessage(null)
    if (!normalizedName) {
      setFormError(t('accountSettings.profile.invalidName'))
      return
    }

    setIsSaving(true)
    try {
      await updateProfile(currentUser.id, normalizedName)
      await refreshUser()
      setSuccessMessage(t('accountSettings.profile.saved'))
    } catch (error) {
      if (error instanceof AccountApiError && error.status === 401) {
        await refreshUser()
      } else if (error instanceof AccountApiError && error.status === 422) {
        setFormError(t('accountSettings.profile.invalidName'))
      } else {
        setFormError(t('accountSettings.profile.saveError'))
      }
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <AccountSettingsLayout activePage="profile">
      <section className="settings-section" aria-labelledby="profile-settings-title">
        <div className="settings-section-heading">
          <h2 id="profile-settings-title">{t('accountSettings.profile.title')}</h2>
          <p>{t('accountSettings.profile.description')}</p>
        </div>
        <form className="settings-form" onSubmit={(event) => void handleSubmit(event)} noValidate>
          <label className="field-label" htmlFor="profile-name">
            {t('accountSettings.profile.name')}
          </label>
          <input
            className="text-input"
            id="profile-name"
            name="name"
            type="text"
            autoComplete="name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            aria-invalid={formError ? true : undefined}
            aria-describedby={formError ? 'profile-error' : undefined}
            disabled={isSaving}
          />

          <div className="readonly-field">
            <span className="field-label">{t('accountSettings.profile.email')}</span>
            <div className="readonly-field-value">
              <span>{currentUser.email}</span>
              <span className={`badge ${currentUser.email_verified_at ? 'badge-success' : 'badge-info'}`}>
                {t(currentUser.email_verified_at
                  ? 'accountSettings.profile.emailVerified'
                  : 'accountSettings.profile.emailUnverified')}
              </span>
            </div>
            <p>{t('accountSettings.profile.emailImmutable')}</p>
          </div>

          {formError ? <div className="alert alert-danger" id="profile-error" role="alert">{formError}</div> : null}
          {successMessage ? <div className="alert alert-info" role="status">{successMessage}</div> : null}
          <button className="button button-primary settings-submit" type="submit" disabled={isSaving}>
            {isSaving ? t('accountSettings.profile.saving') : t('accountSettings.profile.save')}
          </button>
        </form>
      </section>
    </AccountSettingsLayout>
  )
}
