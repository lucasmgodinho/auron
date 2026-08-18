import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import {
  createPlatformAdminOrganization,
  getPlatformAdminStatus,
  listPlatformAdminOrganizationModules,
  listPlatformAdminOrganizations,
  PlatformAdminApiError,
  updatePlatformAdminOrganizationModule,
  type PlatformAdminModule,
  type PlatformAdminOrganization,
} from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AppShell } from '../components/AppShell'
import { LoadingState } from '../components/LoadingState'
import { formatDate } from '../i18n/format'
import { usePageMetadata } from '../hooks/usePageMetadata'
import { usePreferences } from '../preferences/usePreferences'

type PageStatus = 'loading' | 'ready' | 'denied' | 'error'
type ModulePanelStatus = 'idle' | 'loading' | 'ready' | 'error'
type ModuleMessage = { text: string; isError: boolean }
const basicEmailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function AdminPage() {
  const { t } = useTranslation()
  const { locale } = usePreferences()
  const { user, logout, refreshUser } = useAuth()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [organizations, setOrganizations] = useState<PlatformAdminOrganization[]>([])
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [organizationName, setOrganizationName] = useState('')
  const [invitationEmails, setInvitationEmails] = useState([''])
  const [formError, setFormError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [selectedOrganization, setSelectedOrganization] = useState<PlatformAdminOrganization | null>(null)
  const [modules, setModules] = useState<PlatformAdminModule[]>([])
  const [modulePanelStatus, setModulePanelStatus] = useState<ModulePanelStatus>('idle')
  const [updatingModuleKey, setUpdatingModuleKey] = useState<string | null>(null)
  const [moduleMessage, setModuleMessage] = useState<ModuleMessage | null>(null)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  usePageMetadata(t('platformAdmin.meta.title'), t('platformAdmin.meta.description'))

  const loadAdminPage = useCallback(async () => {
    setPageStatus('loading')
    try {
      const isPlatformAdmin = await getPlatformAdminStatus()
      if (!isPlatformAdmin) {
        setPageStatus('denied')
        return
      }
      setOrganizations(await listPlatformAdminOrganizations())
      setPageStatus('ready')
    } catch (error) {
      if (error instanceof PlatformAdminApiError && error.status === 401) {
        await refreshUser()
        return
      }
      setPageStatus('error')
    }
  }, [refreshUser])

  useEffect(() => { void loadAdminPage() }, [loadAdminPage])

  if (user === null) return null
  if (pageStatus === 'loading') {
    return (
      <AppShell
        user={user}
        isLoggingOut={isLoggingOut}
        logoutError={logoutError}
        onLogout={() => void handleLogout()}
      >
        <LoadingState label={t('common.status.loadingContent')} />
      </AppShell>
    )
  }

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
    } catch {
      setLogoutError(t('common.account.logoutError'))
      setIsLoggingOut(false)
    }
  }

  if (pageStatus === 'denied' || pageStatus === 'error') {
    const denied = pageStatus === 'denied'
    return (
      <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()}>
        <section className="status-card content-status-card">
          <p className="eyebrow">{t(denied ? 'platformAdmin.denied.eyebrow' : 'platformAdmin.error.eyebrow')}</p>
          <h1>{t(denied ? 'platformAdmin.denied.title' : 'platformAdmin.error.title')}</h1>
          <p>{t(denied ? 'platformAdmin.denied.body' : 'platformAdmin.error.body')}</p>
          {denied ? (
            <Link className="button button-primary status-link" to="/app">{t('platformAdmin.denied.return')}</Link>
          ) : (
            <button className="button button-primary" type="button" onClick={() => void loadAdminPage()}>{t('common.actions.retry')}</button>
          )}
        </section>
      </AppShell>
    )
  }

  function updateInvitationEmail(index: number, value: string) {
    setInvitationEmails((current) => current.map((email, emailIndex) => (emailIndex === index ? value : email)))
  }

  function removeInvitationEmail(index: number) {
    setInvitationEmails((current) => current.filter((_, emailIndex) => emailIndex !== index))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setFormError(null)
    const normalizedName = organizationName.trim()
    const normalizedEmails = [...new Set(invitationEmails.map((email) => email.trim().toLowerCase()))]
    if (!normalizedName) {
      setFormError(t('platformAdmin.page.invalidName'))
      return
    }
    if (normalizedEmails.length === 0 || normalizedEmails.some((email) => !basicEmailPattern.test(email))) {
      setFormError(t('platformAdmin.page.invalidEmails'))
      return
    }

    setIsSubmitting(true)
    try {
      const organization = await createPlatformAdminOrganization(normalizedName, normalizedEmails)
      setOrganizations((current) => [...current, organization])
      setOrganizationName('')
      setInvitationEmails([''])
      setIsFormOpen(false)
    } catch (error) {
      if (error instanceof PlatformAdminApiError && error.status === 401) await refreshUser()
      else if (error instanceof PlatformAdminApiError && error.status === 422) setFormError(t('platformAdmin.page.invalidPayload'))
      else setFormError(t('platformAdmin.page.createError'))
    } finally {
      setIsSubmitting(false)
    }
  }

  async function openModuleManagement(organization: PlatformAdminOrganization) {
    setSelectedOrganization(organization)
    setModules([])
    setModuleMessage(null)
    setModulePanelStatus('loading')
    try {
      setModules(await listPlatformAdminOrganizationModules(organization.id))
      setModulePanelStatus('ready')
    } catch (error) {
      if (error instanceof PlatformAdminApiError && error.status === 401) await refreshUser()
      else setModulePanelStatus('error')
    }
  }

  async function handleModuleChange(module: PlatformAdminModule, enabled: boolean) {
    if (selectedOrganization === null) return
    setUpdatingModuleKey(module.key)
    setModuleMessage(null)
    try {
      const updated = await updatePlatformAdminOrganizationModule(
        selectedOrganization.id,
        module.key,
        enabled,
      )
      setModules((current) => current.map((item) => (item.key === updated.key ? updated : item)))
      setModuleMessage({ text: t('platformAdmin.modules.updated'), isError: false })
    } catch (error) {
      if (error instanceof PlatformAdminApiError && error.status === 401) await refreshUser()
      else setModuleMessage({ text: t('platformAdmin.modules.updateError'), isError: true })
    } finally {
      setUpdatingModuleKey(null)
    }
  }

  return (
    <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin activePage="admin">
      <header className="page-header page-header-with-action">
        <div>
          <p className="eyebrow">{t('platformAdmin.page.eyebrow')}</p>
          <h1>{t('platformAdmin.page.title')}</h1>
          <p>{t('platformAdmin.page.body')}</p>
        </div>
        <button className="button button-primary" type="button" onClick={() => setIsFormOpen(true)}>
          <span aria-hidden="true">＋ </span>{t('platformAdmin.page.newOrganization')}
        </button>
      </header>

      {isFormOpen ? (
        <section className="form-card" aria-labelledby="new-organization-heading">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{t('platformAdmin.page.provisionEyebrow')}</p>
              <h2 id="new-organization-heading">{t('platformAdmin.page.newOrganization')}</h2>
            </div>
            <button className="button button-secondary" type="button" onClick={() => setIsFormOpen(false)}>{t('common.actions.cancel')}</button>
          </div>
          <form onSubmit={(event) => void handleSubmit(event)}>
            <label className="field-label" htmlFor="organization-name">{t('platformAdmin.page.organizationName')}</label>
            <input id="organization-name" className="text-input" value={organizationName} aria-invalid={formError ? true : undefined} aria-describedby={formError ? 'organization-form-error' : undefined} onChange={(event) => setOrganizationName(event.target.value)} maxLength={255} required />
            <fieldset className="email-fields">
              <legend>{t('platformAdmin.page.initialEmails')}</legend>
              {invitationEmails.map((email, index) => {
                const inputId = `invitation-email-${index}`
                return (
                  <div className="email-field-row" key={inputId}>
                    <label className="sr-only" htmlFor={inputId}>{t('platformAdmin.page.emailLabel', { number: index + 1 })}</label>
                    <input id={inputId} className="text-input" type="email" autoComplete="email" value={email} aria-describedby={formError ? 'organization-form-error' : undefined} onChange={(event) => updateInvitationEmail(index, event.target.value)} required />
                    {invitationEmails.length > 1 ? (
                      <button className="button button-secondary" type="button" onClick={() => removeInvitationEmail(index)}>{t('common.actions.remove')}</button>
                    ) : null}
                  </div>
                )
              })}
              <button className="text-button" type="button" onClick={() => setInvitationEmails((current) => [...current, ''])}>
                <span aria-hidden="true">＋ </span>{t('platformAdmin.page.addEmail')}
              </button>
            </fieldset>
            {formError ? <div className="alert alert-danger" id="organization-form-error" role="alert">{formError}</div> : null}
            <button className="button button-primary" type="submit" disabled={isSubmitting}>{isSubmitting ? t('platformAdmin.page.creating') : t('platformAdmin.page.create')}</button>
          </form>
        </section>
      ) : null}

      <section className="content-section" aria-labelledby="registered-organizations-heading">
        <div className="section-heading">
          <h2 id="registered-organizations-heading">{t('platformAdmin.page.registered')}</h2>
          <span className="badge badge-info">{organizations.length}</span>
        </div>
        {organizations.length === 0 ? (
          <div className="empty-state compact-empty-state"><div className="empty-state-icon" aria-hidden="true">◎</div><p>{t('platformAdmin.page.empty')}</p></div>
        ) : (
          <div className="admin-organization-list">
            {organizations.map((organization) => (
              <article className="admin-organization-card" key={organization.id}>
                <span className="organization-monogram" aria-hidden="true">{organization.name.trim().charAt(0).toUpperCase()}</span>
                <div className="admin-organization-copy"><h3>{organization.name}</h3><p>{t('platformAdmin.page.created', { date: formatDate(organization.created_at, locale) })}</p></div>
                <button className="button button-secondary" type="button" onClick={() => void openModuleManagement(organization)}>
                  {t('platformAdmin.modules.manage')}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>

      {selectedOrganization ? (
        <section className="form-card module-management" aria-labelledby="module-management-heading">
          <div className="section-heading">
            <div>
              <p className="eyebrow">{t('platformAdmin.modules.eyebrow')}</p>
              <h2 id="module-management-heading">{t('platformAdmin.modules.title', { name: selectedOrganization.name })}</h2>
              <p>{t('platformAdmin.modules.description')}</p>
            </div>
            <button className="button button-secondary" type="button" onClick={() => { setSelectedOrganization(null); setModulePanelStatus('idle'); setModuleMessage(null) }}>
              {t('common.actions.close')}
            </button>
          </div>
          {modulePanelStatus === 'loading' ? <LoadingState label={t('platformAdmin.modules.loading')} /> : null}
          {modulePanelStatus === 'error' ? (
            <div className="alert alert-danger" role="alert">
              {t('platformAdmin.modules.loadError')}
              <button className="text-button" type="button" onClick={() => void openModuleManagement(selectedOrganization)}>{t('common.actions.retry')}</button>
            </div>
          ) : null}
          {modulePanelStatus === 'ready' && modules.length === 0 ? (
            <div className="empty-state compact-empty-state"><div className="empty-state-icon" aria-hidden="true">◇</div><p>{t('platformAdmin.modules.empty')}</p></div>
          ) : null}
          {modulePanelStatus === 'ready' && modules.length > 0 ? (
            <div className="module-entitlement-list">
              {modules.map((module) => {
                const moduleName = t(module.name_key, { defaultValue: module.key })
                return (
                  <label className="module-entitlement" key={module.key}>
                    <span><strong>{moduleName}</strong><small>{module.key}</small></span>
                    <span className="module-entitlement-control">
                      <input type="checkbox" checked={module.enabled} disabled={updatingModuleKey !== null} onChange={(event) => void handleModuleChange(module, event.target.checked)} />
                      <span>{t(module.enabled ? 'platformAdmin.modules.enabled' : 'platformAdmin.modules.disabled')}</span>
                    </span>
                  </label>
                )
              })}
            </div>
          ) : null}
          {moduleMessage ? <div className={`alert ${moduleMessage.isError ? 'alert-danger' : 'alert-info'}`} role={moduleMessage.isError ? 'alert' : 'status'}>{moduleMessage.text}</div> : null}
        </section>
      ) : null}
    </AppShell>
  )
}
