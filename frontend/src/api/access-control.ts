export type OrganizationAccessSummary = {
  is_owner: boolean
  enabled_modules: string[]
  permissions: string[]
}

export class AccessControlApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "AccessControlApiError"
    this.status = status
  }
}

export async function getOrganizationAccessSummary(
  organizationId: string,
): Promise<OrganizationAccessSummary> {
  const response = await fetch(
    `/organizations/${encodeURIComponent(organizationId)}/access-control/me`,
    {
      method: "GET",
      credentials: "include",
    },
  )
  if (!response.ok) {
    throw new AccessControlApiError(
      "Unable to load Organization access",
      response.status,
    )
  }
  return (await response.json()) as OrganizationAccessSummary
}
