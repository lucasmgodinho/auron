export type Organization = {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export class OrganizationApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'OrganizationApiError'
    this.status = status
  }
}

export async function listOrganizations(): Promise<Organization[]> {
  const response = await auronFetch('/organizations', {
    method: 'GET',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new OrganizationApiError('Unable to load Organizations', response.status)
  }
  return (await response.json()) as Organization[]
}

export async function getOrganization(organizationId: string): Promise<Organization> {
  const response = await auronFetch(`/organizations/${encodeURIComponent(organizationId)}`, {
    method: 'GET',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new OrganizationApiError('Unable to load the Organization', response.status)
  }
  return (await response.json()) as Organization
}
import { auronFetch } from './http'
