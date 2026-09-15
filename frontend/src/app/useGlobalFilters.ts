import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'

import { CATEGORIES, type Category } from '../api'

export interface GlobalFilters {
  search: string
  provider: string
  category: Category | 'all'
}

function isCategory(value: string | null): value is Category {
  return value !== null && CATEGORIES.some((category) => category === value)
}

export function useGlobalFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo<GlobalFilters>(() => {
    const category = searchParams.get('category')
    return {
      search: searchParams.get('q')?.trim() ?? '',
      provider: searchParams.get('provider')?.trim() ?? '',
      category: isCategory(category) ? category : 'all',
    }
  }, [searchParams])

  const updateFilters = useCallback(
    (patch: Partial<GlobalFilters>) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          const values: GlobalFilters = { ...filters, ...patch }

          if (values.search) next.set('q', values.search)
          else next.delete('q')

          if (values.provider) next.set('provider', values.provider)
          else next.delete('provider')

          if (values.category !== 'all') next.set('category', values.category)
          else next.delete('category')

          next.delete('page')
          return next
        },
        { replace: true },
      )
    },
    [filters, setSearchParams],
  )

  const clearFilters = useCallback(() => {
    setSearchParams({}, { replace: true })
  }, [setSearchParams])

  return {
    filters,
    updateFilters,
    clearFilters,
    hasActiveFilters:
      filters.search !== '' ||
      filters.provider !== '' ||
      filters.category !== 'all',
  }
}
