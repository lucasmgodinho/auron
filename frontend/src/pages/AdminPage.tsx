import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import {
  createPlatformAdminOrganization,
  getPlatformAdminStatus,
  listPlatformAdminOrganizations,
  PlatformAdminApiError,
  type PlatformAdminOrganization,
} from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AuthenticationLoading } from '../components/AuthStatus'
import { AppShell } from '../components/AppShell'

type PageStatus = 'loading' | 'ready' | 'denied' | 'error'

const basicEmailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function AdminPage() {
  const { user, logout, refreshUser } = useAuth()
  const [pageStatus, setPageStatus] = useState<PageStatus>('loading')
  const [organizations, setOrganizations] = useState<PlatformAdminOrganization[]>([])
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [organizationName, setOrganizationName] = useState('')
  const [invitationEmails, setInvitationEmails] = useState([''])
  const [formError, setFormError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

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

  useEffect(() => {
    void loadAdminPage()
  }, [loadAdminPage])

  if (user === null) {
    return null
  }
  if (pageStatus === 'loading') {
    return <AuthenticationLoading />
  }
  if (pageStatus === 'denied') {
    return (
      <div className="status-page">
        <section className="status-card">
          <p className="eyebrow">Access denied</p>
          <h1>Platform Admin access is required</h1>
          <p>Your authenticated account does not have global Auron administration access.</p>
          <Link className="button button-primary status-link" to="/app">Return to Auron</Link>
        </section>
      </div>
    )
  }
  if (pageStatus === 'error') {
    return (
      <div className="status-page">
        <section className="status-card">
          <p className="eyebrow">Admin unavailable</p>
          <h1>We couldn't load Platform Admin</h1>
          <p>Check the backend connection and try again.</p>
          <button className="button button-primary" type="button" onClick={() => void loadAdminPage()}>
            Try again
          </button>
        </section>
      </div>
    )
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

  function updateInvitationEmail(index: number, value: string) {
    setInvitationEmails((current) =>
      current.map((email, emailIndex) => (emailIndex === index ? value : email)),
    )
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
      setFormError('Enter an Organization name.')
      return
    }
    if (normalizedEmails.length === 0 || normalizedEmails.some((email) => !basicEmailPattern.test(email))) {
      setFormError('Enter at least one valid initial access email.')
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
      if (error instanceof PlatformAdminApiError && error.status === 401) {
        await refreshUser()
      } else if (error instanceof PlatformAdminApiError && error.status === 422) {
        setFormError('Check the Organization name and invitation emails.')
      } else {
        setFormError('The Organization could not be created. Please try again.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin
      activePage="admin"
    >
      <section className="admin-heading">
        <div>
          <p className="eyebrow">Auron Admin</p>
          <h1>Organizations</h1>
          <p>Provision customer Organizations and their initial access invitations.</p>
        </div>
        <button className="button button-primary" type="button" onClick={() => setIsFormOpen(true)}>
          + New organization
        </button>
      </section>

      {isFormOpen ? (
        <section className="admin-form-card" aria-labelledby="new-organization-heading">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Provision tenant</p>
              <h2 id="new-organization-heading">New organization</h2>
            </div>
            <button className="button button-secondary" type="button" onClick={() => setIsFormOpen(false)}>
              Cancel
            </button>
          </div>

          <form onSubmit={(event) => void handleSubmit(event)}>
            <label className="field-label" htmlFor="organization-name">Organization name</label>
            <input
              id="organization-name"
              className="text-input"
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              maxLength={255}
              required
            />

            <fieldset className="email-fields">
              <legend>Initial access emails</legend>
              {invitationEmails.map((email, index) => (
                <div className="email-field-row" key={index}>
                  <input
                    className="text-input"
                    type="email"
                    aria-label={`Initial access email ${index + 1}`}
                    value={email}
                    onChange={(event) => updateInvitationEmail(index, event.target.value)}
                    required
                  />
                  {invitationEmails.length > 1 ? (
                    <button className="button button-secondary" type="button" onClick={() => removeInvitationEmail(index)}>
                      Remove
                    </button>
                  ) : null}
                </div>
              ))}
              <button
                className="add-email-button"
                type="button"
                onClick={() => setInvitationEmails((current) => [...current, ''])}
              >
                + Add email
              </button>
            </fieldset>

            {formError ? <p className="inline-error" role="alert">{formError}</p> : null}
            <button className="button button-primary" type="submit" disabled={isSubmitting}>
              {isSubmitting ? 'Creating...' : 'Create organization'}
            </button>
          </form>
        </section>
      ) : null}

      <section className="organization-list" aria-label="Registered Organizations">
        {organizations.length === 0 ? (
          <p className="empty-state">No Organizations have been registered yet.</p>
        ) : (
          organizations.map((organization) => (
            <article className="organization-card" key={organization.id}>
              <h2>{organization.name}</h2>
              <p>Created {new Date(organization.created_at).toLocaleDateString()}</p>
            </article>
          ))
        )}
      </section>
    </AppShell>
  )
}
