import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { StatusPage } from '../components/StatusPage'
import { usePageMetadata } from '../hooks/usePageMetadata'

export function CheckEmailPage() {
  const { t } = useTranslation()
  usePageMetadata(t('auth.meta.checkEmailTitle'), t('auth.meta.checkEmailDescription'))

  return (
    <StatusPage>
      <section className="status-card status-card-centered">
        <div className="status-symbol" aria-hidden="true">✉</div>
        <p className="eyebrow">{t('auth.checkEmail.eyebrow')}</p>
        <h1>{t('auth.checkEmail.title')}</h1>
        <p>{t('auth.checkEmail.body')}</p>
        <Link className="button button-primary status-link" to="/login">{t('auth.checkEmail.return')}</Link>
      </section>
    </StatusPage>
  )
}
