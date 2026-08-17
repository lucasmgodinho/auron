type LoadingStateProps = { label: string }

export function LoadingState({ label }: LoadingStateProps) {
  return (
    <div className="content-loading" aria-live="polite" aria-busy="true">
      <div className="status-indicator" aria-hidden="true" />
      <p>{label}</p>
    </div>
  )
}
