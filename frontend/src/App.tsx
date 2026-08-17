import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from './auth/ProtectedRoute'
import { useAuth } from './auth/useAuth'
import { AuthenticationError, AuthenticationLoading } from './components/AuthStatus'
import { usePageMetadata } from './hooks/usePageMetadata'

const LoginPage = lazy(() =>
  import('./pages/LoginPage').then((module) => ({ default: module.LoginPage })),
)
const RegisterPage = lazy(() =>
  import('./pages/RegisterPage').then((module) => ({ default: module.RegisterPage })),
)
const CheckEmailPage = lazy(() =>
  import('./pages/CheckEmailPage').then((module) => ({ default: module.CheckEmailPage })),
)
const VerifyEmailPage = lazy(() =>
  import('./pages/VerifyEmailPage').then((module) => ({ default: module.VerifyEmailPage })),
)
const AppPage = lazy(() =>
  import('./pages/AppPage').then((module) => ({ default: module.AppPage })),
)
const OrganizationPage = lazy(() =>
  import('./pages/OrganizationPage').then((module) => ({ default: module.OrganizationPage })),
)
const AdminPage = lazy(() =>
  import('./pages/AdminPage').then((module) => ({ default: module.AdminPage })),
)

function AuthenticationRedirect() {
  const { t } = useTranslation()
  const { status, refreshUser } = useAuth()
  usePageMetadata('Auron', t('auth.meta.loginDescription'))

  if (status === 'loading') return <AuthenticationLoading />
  if (status === 'error') return <AuthenticationError onRetry={refreshUser} />
  return <Navigate to={status === 'authenticated' ? '/app' : '/login'} replace />
}

function App() {
  return (
    <Suspense fallback={<AuthenticationLoading />}>
      <Routes>
        <Route path="/" element={<AuthenticationRedirect />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/check-email" element={<CheckEmailPage />} />
        <Route path="/verify-email" element={<VerifyEmailPage />} />
        <Route path="/app" element={<ProtectedRoute><AppPage /></ProtectedRoute>} />
        <Route path="/admin" element={<ProtectedRoute><AdminPage /></ProtectedRoute>} />
        <Route
          path="/app/organizations/:organizationId"
          element={<ProtectedRoute><OrganizationPage /></ProtectedRoute>}
        />
        <Route path="*" element={<AuthenticationRedirect />} />
      </Routes>
    </Suspense>
  )
}

export default App
