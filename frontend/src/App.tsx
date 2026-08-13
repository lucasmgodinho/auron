import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { useAuth } from './auth/useAuth'
import { AuthenticationError, AuthenticationLoading } from './components/AuthStatus'
import { AppPage } from './pages/AppPage'
import { AdminPage } from './pages/AdminPage'
import { CheckEmailPage } from './pages/CheckEmailPage'
import { LoginPage } from './pages/LoginPage'
import { OrganizationPage } from './pages/OrganizationPage'
import { RegisterPage } from './pages/RegisterPage'
import { VerifyEmailPage } from './pages/VerifyEmailPage'

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
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/check-email" element={<CheckEmailPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <AppPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <AdminPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/app/organizations/:organizationId"
        element={
          <ProtectedRoute>
            <OrganizationPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<AuthenticationRedirect />} />
    </Routes>
  )
}

export default App
