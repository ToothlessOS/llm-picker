import { useQuery } from '@tanstack/react-query'
import { Outlet, useLocation } from 'react-router-dom'

import { getMetadata, getOverview } from '../api'
import { AppFooter } from '../components/AppFooter'
import { AppHeader } from '../components/AppHeader'
import { GlobalFilters } from '../components/GlobalFilters'
import { FreshnessBanner } from '../components/states/FreshnessBanner'

export function AppShell() {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const isModelDetail = location.pathname.startsWith('/models/')
  const isCategories = location.pathname.startsWith('/categories')
  const isArtificialAnalysis = location.pathname.startsWith('/artificial-analysis')
  const isDataQuality = location.pathname.startsWith('/data-quality')
  const showFilters = !isHome && !isModelDetail

  const metadataQuery = useQuery({
    queryKey: ['metadata'],
    queryFn: ({ signal }) => getMetadata({ signal }),
    refetchInterval: 60_000,
  })
  const providersQuery = useQuery({
    queryKey: ['provider-options'],
    queryFn: ({ signal }) =>
      getOverview(
        { includeCategories: 'none', pageSize: 200 },
        { signal },
      ),
    select: (response) =>
      Array.from(
        new Set(
          response.results
            .map((row) => row.model.organization)
            .filter((provider): provider is string => provider !== null),
        ),
      ).sort((left, right) => left.localeCompare(right)),
    enabled: showFilters && !isDataQuality,
  })

  return (
    <div className={`application${isHome ? ' application--home' : ''}`}>
      <AppHeader metadata={metadataQuery.data} />
      {showFilters ? (
        <GlobalFilters
          categoryRequiresSelection={isCategories}
          providerOptions={providersQuery.data}
          providerOptionsLoading={providersQuery.isPending}
          showCategory={!isArtificialAnalysis}
          showProvider={!isDataQuality}
        />
      ) : null}
      <FreshnessBanner metadata={metadataQuery.data} />
      <div className="page-container">
        <Outlet />
      </div>
      <AppFooter metadata={metadataQuery.data} />
    </div>
  )
}
