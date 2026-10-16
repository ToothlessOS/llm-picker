import { X } from 'lucide-react'
import { useMemo } from 'react'

import { CATEGORIES, type Category } from '../api'
import { useGlobalFilters } from '../app/useGlobalFilters'
import { SearchField } from './SearchField'

const categoryLabels: Record<Category, string> = {
  agent: 'Agent',
  document: 'Document',
  search: 'Search',
  webdev: 'WebDev',
}

interface GlobalFiltersProps {
  providerOptions?: string[]
  providerOptionsLoading?: boolean
  showCategory?: boolean
  showProvider?: boolean
  categoryRequiresSelection?: boolean
}

export function GlobalFilters({
  providerOptions = [],
  providerOptionsLoading = false,
  showCategory = true,
  showProvider = true,
  categoryRequiresSelection = false,
}: GlobalFiltersProps) {
  const { filters, updateFilters, clearFilters, hasActiveFilters } =
    useGlobalFilters()
  const providers = useMemo(
    () =>
      Array.from(
        new Set(
          filters.provider
            ? [filters.provider, ...providerOptions]
            : providerOptions,
        ),
      ).sort((left, right) => left.localeCompare(right)),
    [filters.provider, providerOptions],
  )

  const selectedCategory =
    categoryRequiresSelection && filters.category === 'all'
      ? 'agent'
      : filters.category

  return (
    <div className="filter-band" aria-label="Global filters">
      <div className="filter-band__inner">
        <SearchField
          label="Find a model"
          onSearchChange={(search) => updateFilters({ search })}
          placeholder="Name or provider"
          value={filters.search}
        />

        {showProvider ? (
          <label className="filter-control">
            <span className="filter-control__label">Provider</span>
            <select
              disabled={providerOptionsLoading && providers.length === 0}
              onChange={(event) => updateFilters({ provider: event.target.value })}
              value={filters.provider}
            >
              <option value="">All providers</option>
              {providers.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        {showCategory ? (
          <label className="filter-control">
            <span className="filter-control__label">Task</span>
            <select
              onChange={(event) =>
                updateFilters({
                  category: event.target.value as Category | 'all',
                })
              }
              value={selectedCategory}
            >
              {!categoryRequiresSelection ? <option value="all">All tasks</option> : null}
              {CATEGORIES.map((category) => (
                <option key={category} value={category}>
                  {categoryLabels[category]}
                </option>
              ))}
            </select>
          </label>
        ) : null}

        <button
          className="filter-clear"
          disabled={!hasActiveFilters}
          onClick={() => clearFilters()}
          title="Clear all filters"
          type="button"
        >
          <X aria-hidden="true" size={17} />
          <span>Clear</span>
        </button>
      </div>
    </div>
  )
}
