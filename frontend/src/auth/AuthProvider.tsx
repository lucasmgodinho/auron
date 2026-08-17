import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import {
  endSession,
  getCurrentUser,
  startGoogleLogin,
  type User,
} from '../api/auth'
import { AuthContext, type AuthContextValue, type AuthStatus } from './auth-context'

type AuthState = {
  user: User | null
  status: AuthStatus
}

type AuthProviderProps = {
  children: ReactNode
}

async function resolveAuthentication(): Promise<AuthState> {
  try {
    const user = await getCurrentUser()
    return user
      ? { user, status: 'authenticated' }
      : { user: null, status: 'unauthenticated' }
  } catch {
    return { user: null, status: 'error' }
  }
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [authState, setAuthState] = useState<AuthState>({
    user: null,
    status: 'loading',
  })

  useEffect(() => {
    let active = true

    void resolveAuthentication().then((nextState) => {
      if (active) {
        setAuthState(nextState)
      }
    })

    return () => {
      active = false
    }
  }, [])

  const refreshUser = useCallback(async () => {
    setAuthState(await resolveAuthentication())
  }, [])

  const logout = useCallback(async () => {
    await endSession()
    setAuthState({ user: null, status: 'unauthenticated' })
  }, [])

  const value = useMemo<AuthContextValue>(
    () => ({
      ...authState,
      refreshUser,
      loginWithGoogle: startGoogleLogin,
      logout,
    }),
    [authState, logout, refreshUser],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
