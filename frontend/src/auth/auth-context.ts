import { createContext } from 'react'

import type { User } from '../api/auth'

export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated' | 'error'

export type AuthContextValue = {
  user: User | null
  status: AuthStatus
  refreshUser: () => Promise<void>
  loginWithGoogle: () => void
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)
