export type User = {
  id: string
  email: string
  name: string
  email_verified_at: string | null
  created_at: string
  updated_at: string
}

export class AuthApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'AuthApiError'
    this.status = status
  }
}

async function parseAuthenticatedUser(response: Response): Promise<User> {
  if (!response.ok) {
    throw new AuthApiError('Authentication request failed', response.status)
  }
  return (await response.json()) as User
}

export async function getCurrentUser(): Promise<User | null> {
  const response = await auronFetch('/auth/me', {
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

export async function loginWithPassword(email: string, password: string): Promise<User> {
  const response = await auronFetch('/auth/login', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  return parseAuthenticatedUser(response)
}

export async function registerLocalAccount(name: string, email: string): Promise<void> {
  const response = await auronFetch('/auth/register', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email }),
  })
  if (!response.ok) {
    throw new AuthApiError('Registration request failed', response.status)
  }
}

export async function completeEmailVerification(token: string, password: string): Promise<User> {
  const response = await auronFetch('/auth/email-verifications/complete', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, password }),
  })
  return parseAuthenticatedUser(response)
}

export async function resendEmailVerification(email: string): Promise<void> {
  const response = await auronFetch('/auth/email-verifications/resend', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!response.ok) {
    throw new AuthApiError('Verification resend failed', response.status)
  }
}

export async function endSession(): Promise<void> {
  const response = await auronFetch('/auth/logout', {
    method: 'POST',
    credentials: 'include',
  })

  if (!response.ok && response.status !== 401) {
    throw new Error('Unable to end the authenticated session')
  }
}
import { auronFetch } from './http'
