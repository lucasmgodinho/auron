type AuthenticationErrorProps = {
  onRetry: () => Promise<void>
}

export function AuthenticationLoading() {
  return (
    <main className="status-page" aria-live="polite" aria-busy="true">
      <div className="status-indicator" aria-hidden="true" />
      <p>Checking your session…</p>
    </main>
  )
}

export function AuthenticationError({ onRetry }: AuthenticationErrorProps) {
  return (
    <main className="status-page" role="alert">
      <div className="status-card">
        <p className="eyebrow">Connection problem</p>
        <h1>We couldn’t connect to the server.</h1>
        <p>Your authentication status could not be verified. Check the backend and try again.</p>
        <button className="button button-primary" type="button" onClick={() => void onRetry()}>
          Retry
        </button>
      </div>
    </main>
  )
}
