import type { ReactNode } from 'react'

import { BrandLogo } from './BrandLogo'
import { PreferenceControls } from './PreferenceControls'

type StatusPageProps = {
  children: ReactNode
}

export function StatusPage({ children }: StatusPageProps) {
  return (
    <main className="status-page" id="main-content">
      <div className="status-topbar">
        <BrandLogo variant="horizontal" eager />
        <PreferenceControls />
      </div>
      {children}
    </main>
  )
}
