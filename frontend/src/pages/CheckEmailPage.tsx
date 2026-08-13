import { Link } from 'react-router-dom'

export function CheckEmailPage() {
  return (
    <main className="status-page">
      <section className="status-card">
        <p className="eyebrow">Account verification</p>
        <h1>Check your email</h1>
        <p>If this email can be used to continue with Auron, we've sent instructions to finish setting up your account.</p>
        <Link className="button button-primary status-link" to="/login">Return to sign in</Link>
      </section>
    </main>
  )
}
