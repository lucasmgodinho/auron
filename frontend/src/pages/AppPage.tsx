import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { acceptOrganizationInvitation, listMyOrganizationInvitations, OrganizationInvitationApiError, type OrganizationInvitation } from '../api/organization-invitations'
import { listOrganizations, OrganizationApiError, type Organization } from '../api/organizations'
import { getPlatformAdminStatus } from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AppShell } from '../components/AppShell'
import { LoadingState } from '../components/LoadingState'
import { formatDateTime } from '../i18n/format'
import { usePageMetadata } from '../hooks/usePageMetadata'
import { usePreferences } from '../preferences/usePreferences'

type AccessSnapshot = { organizations: Organization[]; invitations: OrganizationInvitation[] }
type PageStatus = 'loading' | 'ready' | 'error'

export function AppPage() {
  const { t } = useTranslation()
  const { locale } = usePreferences()
  const { user, logout, refreshUser } = useAuth()
  const navigate = useNavigate()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [organizations, setOrganizations] = useState<Organization[]>([])
  const [invitations, setInvitations] = useState<OrganizationInvitation[]>([])
  const [acceptingInvitationId, setAcceptingInvitationId] = useState<string | null>(null)
  const [invitationErrors, setInvitationErrors] = useState<Record<string, string>>({})
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  usePageMetadata(t('organizations.meta.selectorTitle'), t('organizations.meta.selectorDescription'))

  const loadAccess = useCallback(async (showLoading = true): Promise<AccessSnapshot | null> => {
    if (showLoading) setPageStatus('loading')
    try {
      const [nextOrganizations, nextInvitations] = await Promise.all([
        listOrganizations(),
        listMyOrganizationInvitations(),
      ])
      setOrganizations(nextOrganizations)
      setInvitations(nextInvitations)
      setPageStatus('ready')
      return { organizations: nextOrganizations, invitations: nextInvitations }
    } catch (error) {
      const isUnauthorized =
        (error instanceof OrganizationApiError || error instanceof OrganizationInvitationApiError)
        && error.status === 401
      if (isUnauthorized) {
        await refreshUser()
        return null
      }
      setPageStatus('error')
      return null
    }
  }, [refreshUser])

  useEffect(() => { void loadAccess() }, [loadAccess])

  useEffect(() => {
    let active = true
    void getPlatformAdminStatus()
      .then((hasAccess) => { if (active) setIsPlatformAdmin(hasAccess) })
      .catch(() => { if (active) setIsPlatformAdmin(false) })
    return () => { active = false }
  }, [])

  if (user === null) return null
  if (pageStatus === 'loading') {
    return (
      <AppShell
        user={user}
        isLoggingOut={isLoggingOut}
        logoutError={logoutError}
        onLogout={() => void handleLogout()}
        isPlatformAdmin={isPlatformAdmin}
      >
        <LoadingState label={t('common.status.loadingContent')} />
      </AppShell>
    )
  }
  if (pageStatus === 'error') {
    return (
      <AppShell
        user={user}
        isLoggingOut={isLoggingOut}
        logoutError={logoutError}
        onLogout={() => void handleLogout()}
        isPlatformAdmin={isPlatformAdmin}
      >
        <section className="status-card content-status-card">
          <p className="eyebrow">{t('organizations.loadError.eyebrow')}</p>
          <h1>{t('organizations.loadError.title')}</h1>
          <p>{t('organizations.loadError.body')}</p>
          <button className="button button-primary" type="button" onClick={() => void loadAccess()}>
            {t('common.actions.retry')}
          </button>
        </section>
      </AppShell>
    )
  }
  if (organizations.length === 1 && invitations.length === 0) {
    return <Navigate to={`/app/organizations/${organizations[0].id}`} replace />
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

  async function handleAccept(invitation: OrganizationInvitation) {
    setAcceptingInvitationId(invitation.id)
    setInvitationErrors((current) => ({ ...current, [invitation.id]: '' }))
    try {
      const organization = await acceptOrganizationInvitation(invitation.id)
      await loadAccess(false)
      navigate(`/app/organizations/${organization.id}`)
    } catch (error) {
      if (error instanceof OrganizationInvitationApiError && error.status === 401) {
        await refreshUser()
      } else if (error instanceof OrganizationInvitationApiError && error.status === 403) {
        setInvitationErrors((current) => ({ ...current, [invitation.id]: t('organizations.invitationErrors.forbidden') }))
      } else if (error instanceof OrganizationInvitationApiError && error.status === 409) {
        const snapshot = await loadAccess(false)
        const existingOrganization = snapshot?.organizations.find(
          (organization) => organization.id === invitation.organization_id,
        )
        if (existingOrganization) navigate(`/app/organizations/${existingOrganization.id}`)
        else setInvitationErrors((current) => ({ ...current, [invitation.id]: t('organizations.invitationErrors.accepted') }))
      } else if (error instanceof OrganizationInvitationApiError && error.status === 410) {
        setInvitationErrors((current) => ({ ...current, [invitation.id]: t('organizations.invitationErrors.expired') }))
      } else {
        setInvitationErrors((current) => ({ ...current, [invitation.id]: t('organizations.invitationErrors.unavailable') }))
      }
    } finally {
      setAcceptingInvitationId(null)
    }
  }

  return (
    <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin={isPlatformAdmin}>
      <header className="page-header">
        <p className="eyebrow">{t('organizations.selector.eyebrow')}</p>
        <h1>{t('organizations.selector.welcome', { name: user.name })}</h1>
        <p>{t('organizations.selector.body')}</p>
      </header>

      {invitations.length > 0 ? (
        <section className="content-section" aria-labelledby="invitations-heading">
          <div className="section-heading">
            <div>
              <h2 id="invitations-heading">{t('organizations.selector.invitationsTitle')}</h2>
              <p>{t('organizations.selector.invitationsBody')}</p>
            </div>
            <span className="badge badge-info">{invitations.length}</span>
          </div>
          <div className="card-list">
            {invitations.map((invitation) => (
              <article className="selection-card" key={invitation.id}>
                <div className="selection-card-copy">
                  <h3>{invitation.organization_name}</h3>
                  <p>{t('organizations.selector.expires', { date: formatDateTime(invitation.expires_at, locale) })}</p>
                  {invitationErrors[invitation.id] ? <div className="alert alert-danger" role="alert">{invitationErrors[invitation.id]}</div> : null}
                </div>
                <button className="button button-primary" type="button" disabled={acceptingInvitationId !== null} onClick={() => void handleAccept(invitation)}>
                  {acceptingInvitationId === invitation.id ? t('organizations.selector.accepting') : t('organizations.selector.accept')}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {organizations.length > 0 ? (
        <section className="content-section" aria-labelledby="organizations-heading">
          <div className="section-heading">
            <div>
              <h2 id="organizations-heading">{t('organizations.selector.organizationsTitle')}</h2>
              <p>{t('organizations.selector.organizationsBody')}</p>
            </div>
          </div>
          <div className="organization-grid">
            {organizations.map((organization) => (
              <Link className="organization-tile" key={organization.id} to={`/app/organizations/${organization.id}`}>
                <span className="organization-monogram" aria-hidden="true">{organization.name.trim().charAt(0).toUpperCase()}</span>
                <span className="organization-tile-copy">
                  <strong>{organization.name}</strong>
                  <small>{t('organizations.selector.openHome')}</small>
                </span>
                <span className="tile-arrow" aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {organizations.length === 0 && invitations.length === 0 ? (
        <section className="empty-state" aria-labelledby="no-access-heading">
          <div className="empty-state-icon" aria-hidden="true">◎</div>
          <p className="eyebrow">{t('organizations.selector.noAccessEyebrow')}</p>
          <h2 id="no-access-heading">{t('organizations.selector.noAccessTitle')}</h2>
          <p>{t('organizations.selector.noAccessBody')}</p>
        </section>
      ) : null}
    </AppShell>
  )
}
