import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { BrandLogo } from './BrandLogo'
import { PreferenceControls } from './PreferenceControls'

type AuthLayoutProps = {
  children: ReactNode
  panelEyebrow?: string
  panelTitle?: string
  panelDescription?: string
  labelledBy: string
}

export function AuthLayout({
  children,
  panelEyebrow,
  panelTitle,
  panelDescription,
  labelledBy,
}: AuthLayoutProps) {
  const { t } = useTranslation()

  return (
    <main className="auth-page" id="main-content">
      <section className="auth-layout" aria-labelledby={labelledBy}>
        <div className="auth-brand-panel">
          <BrandLogo variant="vertical" scheme="dark" eager />
          <div className="auth-brand-copy">
            <p className="eyebrow eyebrow-inverse">
              {panelEyebrow ?? t('auth.layout.eyebrow')}
            </p>
            <h1>{panelTitle ?? t('auth.layout.title')}</h1>
            <p>{panelDescription ?? t('auth.layout.description')}</p>
          </div>
        </div>
        <div className="auth-content">
          <div className="auth-preferences" aria-label={t('common.account.preferences')}>
            <PreferenceControls />
          </div>
          <div className="auth-content-inner">{children}</div>
        </div>
      </section>
    </main>
  )
}
