import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  getOrganization,
  OrganizationApiError,
  type Organization,
} from '../api/organizations'
import { getPlatformAdminStatus } from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AuthenticationLoading } from '../components/AuthStatus'
import { AppShell } from '../components/AppShell'

type PageStatus = 'loading' | 'ready' | 'forbidden' | 'not-found' | 'error'

export function OrganizationPage() {
  const { organizationId } = useParams<{ organizationId: string }>()
  const { user, logout, refreshUser } = useAuth()
  const requestId = useRef(0)
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

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
      } else if (
        error instanceof OrganizationApiError
        && (error.status === 404 || error.status === 422)
      ) {
        setPageStatus('not-found')
      } else {
        setPageStatus('error')
      }
    }
  }, [organizationId, refreshUser])

  useEffect(() => {
    void loadOrganization()
    return () => {
      requestId.current += 1
    }
  }, [loadOrganization])

  useEffect(() => {
    let active = true
    void getPlatformAdminStatus()
      .then((hasAccess) => {
        if (active) setIsPlatformAdmin(hasAccess)
      })
      .catch(() => {
        if (active) setIsPlatformAdmin(false)
      })
    return () => {
      active = false
    }
  }, [])

  if (user === null) {
    return null
  }
  if (pageStatus === 'loading') {
    return <AuthenticationLoading />
  }
  if (pageStatus === 'forbidden' || pageStatus === 'not-found' || pageStatus === 'error') {
    const copy = pageStatus === 'forbidden'
      ? {
          eyebrow: 'Access denied',
          heading: 'You cannot access this Organization',
          body: 'Your authenticated account does not have membership in this Organization.',
        }
      : pageStatus === 'not-found'
        ? {
            eyebrow: 'Not found',
            heading: 'Organization not found',
            body: 'The requested Organization does not exist.',
          }
        : {
            eyebrow: 'Organization unavailable',
            heading: 'We could not load this Organization',
            body: 'Check the backend connection and try again.',
          }

    return (
      <div className="status-page">
        <section className="status-card">
          <p className="eyebrow">{copy.eyebrow}</p>
          <h1>{copy.heading}</h1>
          <p>{copy.body}</p>
          {pageStatus === 'error' ? (
            <button className="button button-primary" type="button" onClick={() => void loadOrganization()}>
              Try again
            </button>
          ) : (
            <Link className="button button-primary status-link" to="/app">
              Return to Organizations
            </Link>
          )}
        </section>
      </div>
    )
  }
  if (organization === null) {
    return null
  }

  async function handleLogout() {
    setIsLoggingOut(true)
    setLogoutError(null)
    try {
      await logout()
    } catch {
      setLogoutError('We could not log you out. Please check the server and try again.')
      setIsLoggingOut(false)
    }
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin={isPlatformAdmin}
      organizationName={organization.name}
    >
      <section className="welcome-panel" aria-labelledby="organization-heading">
        <p className="eyebrow">Organization home</p>
        <h1 id="organization-heading">{organization.name}</h1>
        <p>You are viewing this Organization through your current membership.</p>
      </section>

      <section className="next-step-card" aria-labelledby="organization-next-step-heading">
        <div className="next-step-icon" aria-hidden="true">01</div>
        <div>
          <h2 id="organization-next-step-heading">Organization workspace</h2>
          <p>Business modules will appear here as they are implemented.</p>
        </div>
      </section>
    </AppShell>
  )
}
