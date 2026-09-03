import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import App from './App'
import { AuthProvider } from './auth/AuthProvider'
import { DebugNotification } from './debug/DebugNotification'
import './i18n'
import { PreferencesProvider } from './preferences/PreferencesProvider'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <PreferencesProvider>
        <AuthProvider>
          <App />
          <DebugNotification />
        </AuthProvider>
      </PreferencesProvider>
    </BrowserRouter>
  </StrictMode>,
)
