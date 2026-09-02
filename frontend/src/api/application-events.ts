export type ApplicationEvent = {
  id: string
  created_at: string
  level: string
  event: string
  category: string
  module: string | null
  request_id: string | null
  user_id: string | null
  user_name: string | null
  organization_id: string | null
  organization_name: string | null
  resource_type: string | null
  resource_id: string | null
  status: string | null
  duration_ms: number | null
  error_code: string | null
  error_message: string | null
  metadata: Record<string, string | number | boolean | null>
}

export type ApplicationEventPage = {
  items: ApplicationEvent[]
  total: number
  limit: number
  offset: number
}

export type ApplicationEventFilters = {
  dateFrom?: string
  dateTo?: string
  level?: string
  category?: string
  module?: string
  event?: string
  userId?: string
  requestId?: string
}

export class ApplicationEventApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApplicationEventApiError'
    this.status = status
  }
}

export async function listApplicationEvents(
  organizationId: string,
  filters: ApplicationEventFilters,
  limit: number,
  offset: number,
): Promise<ApplicationEventPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (filters.dateFrom) query.set('date_from', `${filters.dateFrom}T00:00:00.000Z`)
  if (filters.dateTo) query.set('date_to', `${filters.dateTo}T23:59:59.999Z`)
  if (filters.level) query.set('level', filters.level)
  if (filters.category) query.set('category', filters.category)
  if (filters.module) query.set('module', filters.module)
  if (filters.event) query.set('event', filters.event)
  if (filters.userId) query.set('user_id', filters.userId)
  if (filters.requestId) query.set('request_id', filters.requestId)

  const response = await fetch(
    `/organizations/${encodeURIComponent(organizationId)}/application-events?${query}`,
    { method: 'GET', credentials: 'include' },
  )
  if (!response.ok) {
    throw new ApplicationEventApiError('Unable to load application events', response.status)
  }
  return (await response.json()) as ApplicationEventPage
}

export async function getApplicationEvent(
  organizationId: string,
  eventId: string,
): Promise<ApplicationEvent> {
  const response = await fetch(
    `/organizations/${encodeURIComponent(organizationId)}/application-events/${encodeURIComponent(eventId)}`,
    { method: 'GET', credentials: 'include' },
  )
  if (!response.ok) {
    throw new ApplicationEventApiError('Unable to load application event', response.status)
  }
  return (await response.json()) as ApplicationEvent
}
