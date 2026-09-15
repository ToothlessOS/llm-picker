import { LoaderCircle } from 'lucide-react'

interface PageHeaderProps {
  title: string
  description: string
  count?: number
  isFetching?: boolean
}

export function PageHeader({
  title,
  description,
  count,
  isFetching = false,
}: PageHeaderProps) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="page-header__status" aria-live="polite">
        {isFetching ? (
          <span className="updating-label">
            <LoaderCircle aria-hidden="true" size={16} /> Updating
          </span>
        ) : null}
        {count !== undefined ? (
          <span className="result-count">{count.toLocaleString()} results</span>
        ) : null}
      </div>
    </header>
  )
}
