import { useContext } from 'react'

import { PreferencesContext, type PreferencesContextValue } from './preferences-context'

export function usePreferences(): PreferencesContextValue {
  const context = useContext(PreferencesContext)
  if (context === undefined) {
    throw new Error('usePreferences must be used within PreferencesProvider')
  }
  return context
}
