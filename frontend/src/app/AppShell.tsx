import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'

import { getMetadata, getOverview } from '../api'
import { AppFooter } from '../components/AppFooter'
import { AppHeader } from '../components/AppHeader'
import { GlobalFilters } from '../components/GlobalFilters'
import { FreshnessBanner } from '../components/states/FreshnessBanner'
import { syncThemeFromSearch } from './theme'

export function AppShell() {
  const location = useLocation()
  const isHome = location.pathname === '/'
  const isInterimCheckIn = location.pathname === '/interim-check-in'
  const isModelDetail = location.pathname.startsWith('/models/')
  const isVisualization = location.pathname.startsWith('/visualizations')
  // The discussion map is a visualization in everything but its URL, and it is
  // the one page that genuinely needs the wider container: three panes, one of
  // which spends 224px of its width on indentation alone.
  const isMap = location.pathname === '/discussions/map'
  const isCategories = location.pathname.startsWith('/categories')
  const isArtificialAnalysis = location.pathname.startsWith('/artificial-analysis')
  const isDataQuality = location.pathname.startsWith('/data-quality')
  // Discussions renders its own search and ordering controls inside the page. The
  // global band's `category` and `provider` parameters are LMArena-specific --
  // `provider` in particular means an organization *string*, where this page's
  // filter means an entity *slug* -- so reusing the band would carry the wrong
  // vocabulary under the same key.
  const isDiscussions = location.pathname.startsWith('/discussions')
  const showFilters =
    !isHome &&
    !isInterimCheckIn &&
    !isModelDetail &&
    !isVisualization &&
    !isDiscussions

  useEffect(() => {
    syncThemeFromSearch(location.search)
  }, [location.search])

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
    <div
      className={`application${isHome ? ' application--home' : ''}${isVisualization || isMap ? ' application--viz' : ''}`}
    >
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
