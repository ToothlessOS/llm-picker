interface LoadingStateProps {
  label?: string
  rows?: number
}

export function LoadingState({ label = 'Loading data', rows = 6 }: LoadingStateProps) {
  return (
    <div className="loading-state" aria-busy="true" aria-live="polite" role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index} aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  )
}
