import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { getOrganizationAccessSummary } from '../api/access-control'
import {
  ApplicationEventApiError,
  getApplicationEvent,
  listApplicationEvents,
  type ApplicationEvent,
  type ApplicationEventFilters,
  type ApplicationEventPage,
} from '../api/application-events'
import { getOrganization, type Organization } from '../api/organizations'
import { getPlatformAdminStatus } from '../api/platform-admin'
import { useAuth } from '../auth/useAuth'
import { AppShell } from '../components/AppShell'
import { LoadingState } from '../components/LoadingState'
import { usePageMetadata } from '../hooks/usePageMetadata'
import { formatDateTime } from '../i18n/format'
import { usePreferences } from '../preferences/usePreferences'

const PAGE_SIZE = 25
const EMPTY_PAGE: ApplicationEventPage = { items: [], total: 0, limit: PAGE_SIZE, offset: 0 }
const EVENT_TRANSLATION_KEYS: Record<string, string> = {
  'api.request.completed': 'applicationLogs.events.apiRequestCompleted',
  'auth.login.succeeded': 'applicationLogs.events.authLoginSucceeded',
  'auth.login.failed': 'applicationLogs.events.authLoginFailed',
  'auth.logout.succeeded': 'applicationLogs.events.authLogoutSucceeded',
  'access.denied': 'applicationLogs.events.accessDenied',
  'access.permissions.changed': 'applicationLogs.events.permissionsChanged',
  'access.group.memberships_changed': 'applicationLogs.events.groupMembershipsChanged',
  'organization.provisioned': 'applicationLogs.events.organizationProvisioned',
  'organization.member.added': 'applicationLogs.events.memberAdded',
  'organization.member.joined': 'applicationLogs.events.memberJoined',
  'organization.member.role_changed': 'applicationLogs.events.memberRoleChanged',
  'module.activated': 'applicationLogs.events.moduleActivated',
  'module.deactivated': 'applicationLogs.events.moduleDeactivated',
  'user.profile.updated': 'applicationLogs.events.profileUpdated',
  'competitive_intelligence.analysis.started': 'applicationLogs.events.analysisStarted',
  'competitive_intelligence.analysis.completed': 'applicationLogs.events.analysisCompleted',
  'competitive_intelligence.analysis.failed': 'applicationLogs.events.analysisFailed',
  'application.error': 'applicationLogs.events.applicationError',
}

type PageStatus = 'loading' | 'ready' | 'forbidden' | 'not-found' | 'error'

function LevelBadge({ level }: { level: string }) {
  return <span className={`event-level event-level-${level}`}>{level}</span>
}

export function OrganizationLogsPage() {
  const { t } = useTranslation()
  const { locale } = usePreferences()
  const { organizationId } = useParams<{ organizationId: string }>()
  const { user, logout, refreshUser } = useAuth()
  const [status, setStatus] = useState<PageStatus>('loading')
  const [organization, setOrganization] = useState<Organization | null>(null)
  const [page, setPage] = useState<ApplicationEventPage>(EMPTY_PAGE)
  const [filters, setFilters] = useState<ApplicationEventFilters>({})
  const [appliedFilters, setAppliedFilters] = useState<ApplicationEventFilters>({})
  const [offset, setOffset] = useState(0)
  const [isLoadingEvents, setIsLoadingEvents] = useState(false)
  const [selectedEvent, setSelectedEvent] = useState<ApplicationEvent | null>(null)
  const [detailError, setDetailError] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false)
  const [competitiveIntelligencePath, setCompetitiveIntelligencePath] = useState<string | undefined>()
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [logoutError, setLogoutError] = useState<string | null>(null)

  usePageMetadata(t('applicationLogs.meta.title'), t('applicationLogs.meta.description'))

  function eventLabel(event: string) {
    const translationKey = EVENT_TRANSLATION_KEYS[event]
    return translationKey ? t(translationKey) : event
  }

  const loadEvents = useCallback(async () => {
    if (!organizationId) return
    setIsLoadingEvents(true)
    try {
      setPage(await listApplicationEvents(organizationId, appliedFilters, PAGE_SIZE, offset))
    } catch (error) {
      if (error instanceof ApplicationEventApiError && error.status === 401) await refreshUser()
      else setStatus(error instanceof ApplicationEventApiError && error.status === 403 ? 'forbidden' : 'error')
    } finally {
      setIsLoadingEvents(false)
    }
  }, [appliedFilters, offset, organizationId, refreshUser])

  useEffect(() => {
    let active = true
    if (!organizationId) {
      setStatus('not-found')
      return () => { active = false }
    }
    void Promise.all([
      getOrganization(organizationId),
      getOrganizationAccessSummary(organizationId),
    ]).then(([nextOrganization, access]) => {
      if (!active) return
      if (!['owner', 'admin'].includes(access.membership_role)) {
        setStatus('forbidden')
        return
      }
      const canRunCompetitiveIntelligence = access.is_owner
        || access.permissions.includes('competitive_intelligence.analysis.run')
      setCompetitiveIntelligencePath(
        access.enabled_modules.includes('competitive_intelligence') && canRunCompetitiveIntelligence
          ? `/app/organizations/${organizationId}/modules/competitive-intelligence`
          : undefined,
      )
      setOrganization(nextOrganization)
      setStatus('ready')
    }).catch(() => { if (active) setStatus('error') })
    return () => { active = false }
  }, [organizationId])

  useEffect(() => {
    if (status === 'ready') void loadEvents()
  }, [loadEvents, status])

  useEffect(() => {
    let active = true
    void getPlatformAdminStatus()
      .then((hasAccess) => { if (active) setIsPlatformAdmin(hasAccess) })
      .catch(() => { if (active) setIsPlatformAdmin(false) })
    return () => { active = false }
  }, [])

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

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setOffset(0)
    setSelectedEvent(null)
    setAppliedFilters({ ...filters })
  }

  async function openDetails(eventId: string) {
    if (!organizationId) return
    setDetailError(false)
    try {
      setSelectedEvent(await getApplicationEvent(organizationId, eventId))
      setCopied(false)
    } catch {
      setDetailError(true)
    }
  }

  async function copyRequestId() {
    if (!selectedEvent?.request_id) return
    try {
      await navigator.clipboard.writeText(selectedEvent.request_id)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  if (user === null) return null
  const logsPath = organizationId ? `/app/organizations/${organizationId}/logs` : undefined

  if (status === 'loading') {
    return (
      <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin={isPlatformAdmin}>
        <LoadingState label={t('common.status.loadingContent')} />
      </AppShell>
    )
  }

  if (status !== 'ready' || organization === null) {
    return (
      <AppShell user={user} isLoggingOut={isLoggingOut} logoutError={logoutError} onLogout={() => void handleLogout()} isPlatformAdmin={isPlatformAdmin}>
        <section className="status-card content-status-card">
          <p className="eyebrow">{t('applicationLogs.access.eyebrow')}</p>
          <h1>{t(`applicationLogs.access.${status === 'forbidden' ? 'forbidden' : 'error'}Title`)}</h1>
          <p>{t(`applicationLogs.access.${status === 'forbidden' ? 'forbidden' : 'error'}Body`)}</p>
          <Link className="button button-primary status-link" to="/app">{t('organizations.home.return')}</Link>
        </section>
      </AppShell>
    )
  }

  const hasNextPage = offset + page.items.length < page.total
  return (
    <AppShell
      user={user}
      isLoggingOut={isLoggingOut}
      logoutError={logoutError}
      onLogout={() => void handleLogout()}
      isPlatformAdmin={isPlatformAdmin}
      activePage="applicationLogs"
      organizationName={organization.name}
      competitiveIntelligencePath={competitiveIntelligencePath}
      applicationLogsPath={logsPath}
    >
      <header className="page-header organization-page-header">
        <p className="eyebrow">{t('applicationLogs.page.eyebrow')}</p>
        <h1>{t('applicationLogs.page.title')}</h1>
        <p>{t('applicationLogs.page.description')}</p>
      </header>

      <section className="form-card application-log-filters" aria-labelledby="event-filter-heading">
        <h2 id="event-filter-heading">{t('applicationLogs.filters.title')}</h2>
        <form onSubmit={applyFilters}>
          <div className="application-log-filter-grid">
            <label><span>{t('applicationLogs.filters.dateFrom')}</span><input className="text-input" type="date" value={filters.dateFrom ?? ''} onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.dateTo')}</span><input className="text-input" type="date" value={filters.dateTo ?? ''} onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.level')}</span><select value={filters.level ?? ''} onChange={(event) => setFilters((current) => ({ ...current, level: event.target.value }))}><option value="">{t('applicationLogs.filters.all')}</option><option value="info">info</option><option value="warning">warning</option><option value="error">error</option><option value="critical">critical</option></select></label>
            <label><span>{t('applicationLogs.filters.category')}</span><input className="text-input" value={filters.category ?? ''} onChange={(event) => setFilters((current) => ({ ...current, category: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.module')}</span><input className="text-input" value={filters.module ?? ''} onChange={(event) => setFilters((current) => ({ ...current, module: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.event')}</span><input className="text-input" value={filters.event ?? ''} onChange={(event) => setFilters((current) => ({ ...current, event: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.user')}</span><input className="text-input" value={filters.userId ?? ''} onChange={(event) => setFilters((current) => ({ ...current, userId: event.target.value }))} /></label>
            <label><span>{t('applicationLogs.filters.requestId')}</span><input className="text-input" value={filters.requestId ?? ''} onChange={(event) => setFilters((current) => ({ ...current, requestId: event.target.value }))} /></label>
          </div>
          <button className="button button-primary" type="submit" disabled={isLoadingEvents}>{t('applicationLogs.filters.apply')}</button>
        </form>
      </section>

      <section className="content-section application-log-list" aria-labelledby="event-list-heading">
        <div className="section-heading"><h2 id="event-list-heading">{t('applicationLogs.list.title')}</h2><span className="badge badge-info">{page.total}</span></div>
        {isLoadingEvents ? <LoadingState label={t('applicationLogs.list.loading')} /> : null}
        {!isLoadingEvents && page.items.length === 0 ? <div className="empty-state compact-empty-state"><p>{t('applicationLogs.list.empty')}</p></div> : null}
        {!isLoadingEvents && page.items.length > 0 ? (
          <div className="application-log-table-wrap">
            <table className="application-log-table">
              <thead><tr><th>{t('applicationLogs.list.timestamp')}</th><th>{t('applicationLogs.list.level')}</th><th>{t('applicationLogs.list.event')}</th><th>{t('applicationLogs.list.status')}</th><th>{t('applicationLogs.list.duration')}</th><th><span className="sr-only">{t('applicationLogs.list.details')}</span></th></tr></thead>
              <tbody>{page.items.map((item) => (
                <tr key={item.id}><td>{formatDateTime(item.created_at, locale)}</td><td><LevelBadge level={item.level} /></td><td><strong>{eventLabel(item.event)}</strong><small>{item.module ?? item.category}</small></td><td>{item.status ?? '—'}</td><td>{item.duration_ms === null ? '—' : `${item.duration_ms} ms`}</td><td><button className="text-button" type="button" onClick={() => void openDetails(item.id)}>{t('applicationLogs.list.details')}</button></td></tr>
              ))}</tbody>
            </table>
          </div>
        ) : null}
        <div className="application-log-pagination">
          <button className="button button-secondary" type="button" disabled={offset === 0 || isLoadingEvents} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{t('applicationLogs.pagination.previous')}</button>
          <span>{t('applicationLogs.pagination.position', { from: page.total === 0 ? 0 : offset + 1, to: offset + page.items.length, total: page.total })}</span>
          <button className="button button-secondary" type="button" disabled={!hasNextPage || isLoadingEvents} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('applicationLogs.pagination.next')}</button>
        </div>
      </section>

      {detailError ? <div className="alert alert-danger" role="alert">{t('applicationLogs.details.error')}</div> : null}
      {selectedEvent ? (
        <aside className="application-log-details" aria-labelledby="event-detail-heading">
          <div className="section-heading"><div><p className="eyebrow">{t('applicationLogs.details.eyebrow')}</p><h2 id="event-detail-heading">{eventLabel(selectedEvent.event)}</h2></div><button className="button button-secondary" type="button" onClick={() => setSelectedEvent(null)}>{t('common.actions.close')}</button></div>
          <dl><div><dt>{t('applicationLogs.list.timestamp')}</dt><dd>{formatDateTime(selectedEvent.created_at, locale)}</dd></div><div><dt>{t('applicationLogs.list.level')}</dt><dd><LevelBadge level={selectedEvent.level} /></dd></div><div><dt>{t('applicationLogs.details.user')}</dt><dd>{selectedEvent.user_name ?? selectedEvent.user_id ?? '—'}</dd></div><div><dt>{t('applicationLogs.filters.module')}</dt><dd>{selectedEvent.module ?? '—'}</dd></div><div><dt>{t('applicationLogs.details.resource')}</dt><dd>{selectedEvent.resource_type ? `${selectedEvent.resource_type}: ${selectedEvent.resource_id ?? '—'}` : '—'}</dd></div><div><dt>{t('applicationLogs.list.duration')}</dt><dd>{selectedEvent.duration_ms === null ? '—' : `${selectedEvent.duration_ms} ms`}</dd></div><div><dt>{t('applicationLogs.filters.requestId')}</dt><dd><code>{selectedEvent.request_id ?? '—'}</code>{selectedEvent.request_id ? <button className="text-button" type="button" onClick={() => void copyRequestId()}>{t(copied ? 'applicationLogs.details.copied' : 'applicationLogs.details.copy')}</button> : null}</dd></div></dl>
          {selectedEvent.error_message ? <div className="alert alert-danger"><strong>{selectedEvent.error_code}</strong><span>{selectedEvent.error_message}</span></div> : null}
          {Object.keys(selectedEvent.metadata).length > 0 ? <div><h3>{t('applicationLogs.details.metadata')}</h3><dl>{Object.entries(selectedEvent.metadata).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl></div> : null}
        </aside>
      ) : null}
    </AppShell>
  )
}
