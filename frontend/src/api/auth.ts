export type User = {
  id: string
  email: string
  name: string
  created_at: string
  updated_at: string
}

export async function getCurrentUser(): Promise<User | null> {
  const response = await fetch('/auth/me', {
    method: 'GET',
    credentials: 'include',
  })

  if (response.status === 401) {
    return null
  }
  if (!response.ok) {
    throw new Error('Unable to load the authenticated user')
  }

  return (await response.json()) as User
}

export function startGoogleLogin(): void {
  window.location.assign('/auth/google/login')
}

export async function endSession(): Promise<void> {
  const response = await fetch('/auth/logout', {
    method: 'POST',
    credentials: 'include',
  })

  if (!response.ok && response.status !== 401) {
    throw new Error('Unable to end the authenticated session')
  }
}
