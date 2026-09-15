import { SearchX, X } from 'lucide-react'

interface EmptyStateProps {
  onClear?: () => void
  title?: string
  message?: string
}

export function EmptyState({
  onClear,
  title = 'No matching models',
  message = 'The current filters returned no data.',
}: EmptyStateProps) {
  return (
    <div className="state-message" role="status">
      <SearchX aria-hidden="true" size={28} strokeWidth={1.6} />
      <h2>{title}</h2>
      <p>{message}</p>
      {onClear ? (
        <button className="button button--secondary" onClick={onClear} type="button">
          <X aria-hidden="true" size={16} />
          Clear filters
        </button>
      ) : null}
    </div>
  )
}
