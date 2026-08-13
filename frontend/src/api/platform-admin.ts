export type PlatformAdminOrganization = {
  id: string
  name: string
  created_at: string
  updated_at: string
}

export class PlatformAdminApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'PlatformAdminApiError'
    this.status = status
  }
}

export async function getPlatformAdminStatus(): Promise<boolean> {
  const response = await fetch('/platform-admin/me', {
    method: 'GET',
    credentials: 'include',
  })

  if (response.status === 403) {
    return false
  }
  if (!response.ok) {
    throw new PlatformAdminApiError('Unable to verify Platform Admin access', response.status)
  }

  const status = (await response.json()) as { is_platform_admin: boolean }
  return status.is_platform_admin
}

export async function listPlatformAdminOrganizations(): Promise<PlatformAdminOrganization[]> {
  const response = await fetch('/platform-admin/organizations', {
    method: 'GET',
    credentials: 'include',
  })

  if (!response.ok) {
    throw new PlatformAdminApiError('Unable to load Organizations', response.status)
  }
  return (await response.json()) as PlatformAdminOrganization[]
}

export async function createPlatformAdminOrganization(
  name: string,
  invitationEmails: string[],
): Promise<PlatformAdminOrganization> {
  const response = await fetch('/platform-admin/organizations', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      invitation_emails: invitationEmails,
    }),
  })

  if (!response.ok) {
    throw new PlatformAdminApiError('Unable to create the Organization', response.status)
  }
  return (await response.json()) as PlatformAdminOrganization
}
