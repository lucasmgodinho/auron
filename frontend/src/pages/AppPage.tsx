import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import {
  acceptOrganizationInvitation,
  listMyOrganizationInvitations,
  OrganizationInvitationApiError,
  type OrganizationInvitation,
} from '../api/organization-invitations'
import {
  listOrganizations,
  OrganizationApiError,
  type Organization,
} from '../api/organizations'
import { getPlatformAdminStatus } from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AuthenticationLoading } from '../components/AuthStatus'
import { AppShell } from '../components/AppShell'

type AccessSnapshot = {
  organizations: Organization[]
  invitations: OrganizationInvitation[]
}

type PageStatus = 'loading' | 'ready' | 'error'

export function AppPage() {
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

  useEffect(() => {
    void loadAccess()
  }, [loadAccess])

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
  if (pageStatus === 'error') {
    return (
      <div className="status-page">
        <section className="status-card">
          <p className="eyebrow">Organizations unavailable</p>
          <h1>We could not load your access</h1>
          <p>Check the backend connection and try again.</p>
          <button className="button button-primary" type="button" onClick={() => void loadAccess()}>
            Try again
          </button>
        </section>
      </div>
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
      setLogoutError('We could not log you out. Please check the server and try again.')
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
        setInvitationErrors((current) => ({
          ...current,
          [invitation.id]: 'This invitation is not available to your account.',
        }))
      } else if (error instanceof OrganizationInvitationApiError && error.status === 409) {
        const snapshot = await loadAccess(false)
        const existingOrganization = snapshot?.organizations.find(
          (organization) => organization.id === invitation.organization_id,
        )
        if (existingOrganization) {
          navigate(`/app/organizations/${existingOrganization.id}`)
        } else {
          setInvitationErrors((current) => ({
            ...current,
            [invitation.id]: 'This invitation was already accepted. Your access has been refreshed.',
          }))
        }
      } else if (error instanceof OrganizationInvitationApiError && error.status === 410) {
        setInvitationErrors((current) => ({
          ...current,
          [invitation.id]: 'This invitation has expired. Ask a Platform Admin to reissue it.',
        }))
      } else {
        setInvitationErrors((current) => ({
          ...current,
          [invitation.id]: 'The invitation could not be accepted. Check your connection and try again.',
        }))
      }
    } finally {
      setAcceptingInvitationId(null)
    }
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin={isPlatformAdmin}
    >
      <section className="access-heading">
        <p className="eyebrow">Organization access</p>
        <h1>Welcome, {user.name}</h1>
        <p>Select an Organization or review an invitation to continue.</p>
      </section>

      {invitations.length > 0 ? (
        <section className="access-section" aria-labelledby="invitations-heading">
          <div className="section-heading">
            <div>
              <h2 id="invitations-heading">Pending invitations</h2>
              <p>Accept an invitation to join that Organization.</p>
            </div>
          </div>
          <div className="access-card-list">
            {invitations.map((invitation) => (
              <article className="access-card" key={invitation.id}>
                <div>
                  <h3>{invitation.organization_name}</h3>
                  <p>Expires {new Date(invitation.expires_at).toLocaleString()}</p>
                  {invitationErrors[invitation.id] ? (
                    <p className="card-error" role="alert">{invitationErrors[invitation.id]}</p>
                  ) : null}
                </div>
                <button
                  className="button button-primary"
                  type="button"
                  disabled={acceptingInvitationId !== null}
                  onClick={() => void handleAccept(invitation)}
                >
                  {acceptingInvitationId === invitation.id ? 'Accepting...' : 'Accept invitation'}
                </button>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {organizations.length > 0 ? (
        <section className="access-section" aria-labelledby="organizations-heading">
          <div className="section-heading">
            <div>
              <h2 id="organizations-heading">Your Organizations</h2>
              <p>Choose the Organization you want to open.</p>
            </div>
          </div>
          <div className="access-card-list">
            {organizations.map((organization) => (
              <Link
                className="access-card organization-choice"
                key={organization.id}
                to={`/app/organizations/${organization.id}`}
              >
                <div>
                  <h3>{organization.name}</h3>
                  <p>Open Organization home</p>
                </div>
                <span aria-hidden="true">Open</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      {organizations.length === 0 && invitations.length === 0 ? (
        <section className="empty-access" aria-labelledby="no-access-heading">
          <p className="eyebrow">No Organization access</p>
          <h2 id="no-access-heading">You do not have Organization access yet</h2>
          <p>A Platform Admin can invite your authenticated email address to an Organization.</p>
        </section>
      ) : null}
    </AppShell>
  )
}
