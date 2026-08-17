import type { User } from './auth'

export type AccountSettings = {
  user: Pick<User, 'id' | 'email' | 'name' | 'email_verified_at'>
  authentication_methods: {
    password: boolean
    google: boolean
  }
}

export class AccountApiError extends Error {
  status: number
  detail: string | null

  constructor(message: string, status: number, detail: string | null = null) {
    super(message)
    this.name = 'AccountApiError'
    this.status = status
    this.detail = detail
  }
}

async function accountError(response: Response, message: string): Promise<AccountApiError> {
  let detail: string | null = null
  try {
    const payload = (await response.json()) as { detail?: unknown }
    if (typeof payload.detail === 'string') detail = payload.detail
  } catch {
    // A non-JSON infrastructure response is represented by the fallback message.
  }
  return new AccountApiError(message, response.status, detail)
}

export async function getAccountSettings(): Promise<AccountSettings> {
  const response = await fetch('/auth/account', {
    method: 'GET',
    credentials: 'include',
  })
  if (!response.ok) throw await accountError(response, 'Unable to load account settings')
  return (await response.json()) as AccountSettings
}

export async function updateProfile(userId: string, name: string): Promise<User> {
  const response = await fetch(`/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (!response.ok) throw await accountError(response, 'Unable to update profile')
  return (await response.json()) as User
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const response = await fetch('/auth/password/change', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
  if (!response.ok) throw await accountError(response, 'Unable to change password')
}

export async function startPasswordEnrollment(): Promise<void> {
  const response = await fetch('/auth/password/enrollment/start', {
    method: 'POST',
    credentials: 'include',
  })
  if (!response.ok) throw await accountError(response, 'Unable to start password enrollment')
}
