import type { Organization } from './organizations'

export type OrganizationInvitation = {
  id: string
  organization_id: string
  organization_name: string
  expires_at: string
}

export class OrganizationInvitationApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'OrganizationInvitationApiError'
    this.status = status
  }
}

export async function listMyOrganizationInvitations(): Promise<OrganizationInvitation[]> {
  const response = await fetch('/organization-invitations/me', {
    method: 'GET',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new OrganizationInvitationApiError('Unable to load invitations', response.status)
  }
  return (await response.json()) as OrganizationInvitation[]
}

export async function acceptOrganizationInvitation(invitationId: string): Promise<Organization> {
  const response = await fetch(
    `/organization-invitations/${encodeURIComponent(invitationId)}/accept`,
    {
      method: 'POST',
      credentials: 'include',
    },
  )

  if (!response.ok) {
    throw new OrganizationInvitationApiError('Unable to accept the invitation', response.status)
  }
  return (await response.json()) as Organization
}
