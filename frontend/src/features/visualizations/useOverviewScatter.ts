import { useQuery } from '@tanstack/react-query'

import { getOverview, type ApiRequestOptions, type OverviewResponse } from '../../api'
import { buildCostBarModel, costBarSourcesFromOverview } from './costBars'
import { buildModelCardCatalog, modelCardSourcesFromOverview } from './modelCard'
import { buildScatterModel, scatterSourcesFromOverview } from './scatter'
import { buildTaskFitModel, taskFitSourcesFromOverview } from './taskFit'

export const OVERVIEW_VIZ_QUERY_KEY = ['overview', 'viz', 'all-categories'] as const
export const OVERVIEW_SCATTER_QUERY_KEY = OVERVIEW_VIZ_QUERY_KEY

function fetchOverviewViz(options?: ApiRequestOptions): Promise<OverviewResponse> {
  return getOverview(
    {
      includeCategories: 'all',
      ordering: ['aa_cost_per_task'],
      pageSize: 200,
    },
    options,
  )
}

export function useOverviewScatter() {
  return useQuery({
    queryKey: OVERVIEW_VIZ_QUERY_KEY,
    queryFn: ({ signal }) => fetchOverviewViz({ signal }),
    select: (response) =>
      buildScatterModel(scatterSourcesFromOverview(response.results)),
  })
}

export function useOverviewCostBars() {
  return useQuery({
    queryKey: OVERVIEW_VIZ_QUERY_KEY,
    queryFn: ({ signal }) => fetchOverviewViz({ signal }),
    select: (response) =>
      buildCostBarModel(costBarSourcesFromOverview(response.results)),
  })
}

export function useOverviewTaskFit() {
  return useQuery({
    queryKey: OVERVIEW_VIZ_QUERY_KEY,
    queryFn: ({ signal }) => fetchOverviewViz({ signal }),
    select: (response) =>
      buildTaskFitModel(taskFitSourcesFromOverview(response.results)),
  })
}

export function useOverviewModelCard() {
  return useQuery({
    queryKey: OVERVIEW_VIZ_QUERY_KEY,
    queryFn: ({ signal }) => fetchOverviewViz({ signal }),
    select: (response) =>
      buildModelCardCatalog(modelCardSourcesFromOverview(response.results)),
  })
}
