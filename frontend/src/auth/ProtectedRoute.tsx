import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'

import { AuthenticationError, AuthenticationLoading } from '../components/AuthStatus'
import { useAuth } from './useAuth'

type ProtectedRouteProps = {
  children: ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { status, refreshUser } = useAuth()

  if (status === 'loading') {
    return <AuthenticationLoading />
  }
  if (status === 'error') {
    return <AuthenticationError onRetry={refreshUser} />
  }
  if (status === 'unauthenticated') {
    return <Navigate to="/login" replace />
  }

  return children
}
