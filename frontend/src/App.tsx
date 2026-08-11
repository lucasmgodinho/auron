import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { useAuth } from './auth/useAuth'
import { AuthenticationError, AuthenticationLoading } from './components/AuthStatus'
import { AppPage } from './pages/AppPage'
import { LoginPage } from './pages/LoginPage'

function AuthenticationRedirect() {
  const { status, refreshUser } = useAuth()

  if (status === 'loading') {
    return <AuthenticationLoading />
  }
  if (status === 'error') {
    return <AuthenticationError onRetry={refreshUser} />
  }
  return <Navigate to={status === 'authenticated' ? '/app' : '/login'} replace />
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<AuthenticationRedirect />} />
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<AuthenticationRedirect />} />
    </Routes>
  )
}

export default App
