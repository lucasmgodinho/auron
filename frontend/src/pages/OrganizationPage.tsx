import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { getOrganization, OrganizationApiError, type Organization } from '../api/organizations'
import { getPlatformAdminStatus } from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AppShell } from '../components/AppShell'
import { LoadingState } from '../components/LoadingState'
import { usePageMetadata } from '../hooks/usePageMetadata'

type PageStatus = 'loading' | 'ready' | 'forbidden' | 'not-found' | 'error'

export function OrganizationPage() {
  const { t } = useTranslation()
  const { organizationId } = useParams<{ organizationId: string }>()
  const { user, logout, refreshUser } = useAuth()
  const requestId = useRef(0)
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)
  const metadataName = organization?.name ?? t('organizations.meta.selectorTitle')
  usePageMetadata(
    metadataName,
    organization
      ? t('organizations.meta.homeDescription', { name: organization.name })
      : t('organizations.meta.selectorDescription'),
  )

  const loadOrganization = useCallback(async () => {
    const currentRequestId = ++requestId.current
    setPageStatus('loading')
    setOrganization(null)
    if (!organizationId) {
      setPageStatus('not-found')
      return
    }
    try {
      const nextOrganization = await getOrganization(organizationId)
      if (requestId.current === currentRequestId) {
        setOrganization(nextOrganization)
        setPageStatus('ready')
      }
    } catch (error) {
      if (requestId.current !== currentRequestId) return
      if (error instanceof OrganizationApiError && error.status === 401) {
        await refreshUser()
        if (requestId.current === currentRequestId) setPageStatus('error')
      } else if (error instanceof OrganizationApiError && error.status === 403) {
        setPageStatus('forbidden')
      } else if (error instanceof OrganizationApiError && (error.status === 404 || error.status === 422)) {
        setPageStatus('not-found')
      } else {
        setPageStatus('error')
      }
    }
  }, [organizationId, refreshUser])

  useEffect(() => {
    void loadOrganization()
    return () => { requestId.current += 1 }
  }, [loadOrganization])

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

  if (pageStatus === 'forbidden' || pageStatus === 'not-found' || pageStatus === 'error') {
    const copy = pageStatus === 'forbidden'
      ? { eyebrow: t('organizations.home.deniedEyebrow'), heading: t('organizations.home.deniedTitle'), body: t('organizations.home.deniedBody') }
      : pageStatus === 'not-found'
        ? { eyebrow: t('organizations.home.notFoundEyebrow'), heading: t('organizations.home.notFoundTitle'), body: t('organizations.home.notFoundBody') }
        : { eyebrow: t('organizations.home.errorEyebrow'), heading: t('organizations.home.errorTitle'), body: t('organizations.home.errorBody') }

    return (
      <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin={isPlatformAdmin}>
        <section className="status-card content-status-card">
          <p className="eyebrow">{copy.eyebrow}</p>
          <h1>{copy.heading}</h1>
          <p>{copy.body}</p>
          {pageStatus === 'error' ? (
            <button className="button button-primary" type="button" onClick={() => void loadOrganization()}>{t('common.actions.retry')}</button>
          ) : (
            <Link className="button button-primary status-link" to="/app">{t('organizations.home.return')}</Link>
          )}
        </section>
      </AppShell>
    )
  }
  if (organization === null) return null

  return (
    <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin={isPlatformAdmin} organizationName={organization.name}>
      <header className="page-header organization-page-header">
        <p className="eyebrow">{t('organizations.home.eyebrow')}</p>
        <h1>{organization.name}</h1>
        <p>{t('organizations.home.body')}</p>
      </header>
      <section className="ready-card" aria-labelledby="organization-ready-heading">
        <div className="ready-icon" aria-hidden="true">✓</div>
        <div>
          <span className="badge badge-success">Auron</span>
          <h2 id="organization-ready-heading">{t('organizations.home.readyTitle')}</h2>
          <p>{t('organizations.home.readyBody')}</p>
        </div>
      </section>
    </AppShell>
  )
}
