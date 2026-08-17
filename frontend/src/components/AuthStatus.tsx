import { useTranslation } from 'react-i18next'

import { StatusPage } from './StatusPage'

type AuthenticationErrorProps = { onRetry: () => Promise<void> }

export function AuthenticationLoading() {
  const { t } = useTranslation()
  return (
    <StatusPage>
      <div className="loading-state" aria-live="polite" aria-busy="true">
        <div className="status-indicator" aria-hidden="true" />
        <p>{t('common.status.checkingSession')}</p>
      </div>
    </StatusPage>
  )
}

export function AuthenticationError({ onRetry }: AuthenticationErrorProps) {
  const { t } = useTranslation()
  return (
    <StatusPage>
      <section className="status-card" role="alert">
        <p className="eyebrow">{t('common.status.connectionEyebrow')}</p>
        <h1>{t('common.status.connectionTitle')}</h1>
        <p>{t('common.status.connectionBody')}</p>
        <button className="button button-primary" type="button" onClick={() => void onRetry()}>
          {t('common.actions.retry')}
        </button>
      </section>
    </StatusPage>
  )
}
