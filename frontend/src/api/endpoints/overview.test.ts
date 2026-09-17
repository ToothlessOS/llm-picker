import { describe, expect, it, vi } from 'vitest'

import {
  OVERVIEW_PAGE_LIMIT,
  collectPaginatedOverview,
  type OverviewResponse,
} from './overview'

function fakePage(keys: string[], next: string | null): OverviewResponse {
  return {
    count: 3,
    next,
    previous: null,
    page_size: 2,
    results: keys.map((key) => ({ model: { key } })) as OverviewResponse['results'],
    meta: {
      generated_at: '2026-09-15T00:00:00Z',
      sources: {} as OverviewResponse['meta']['sources'],
      categories_included: [],
    },
  }
}

describe('collectPaginatedOverview', () => {
  it('returns a single page when next is null', async () => {
    const fetchPage = vi.fn().mockResolvedValue(fakePage(['a', 'b'], null))

    const response = await collectPaginatedOverview(fetchPage, { pageSize: 2 })

    expect(fetchPage).toHaveBeenCalledTimes(1)
    expect(fetchPage).toHaveBeenCalledWith({ page: 1, pageSize: 2 }, undefined)
    expect(response.results.map((row) => row.model.key)).toEqual(['a', 'b'])
    expect(response.next).toBeNull()
  })

  it('follows next until the listing is exhausted', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValueOnce(fakePage(['a', 'b'], 'https://example.test/overview/?page=2'))
      .mockResolvedValueOnce(fakePage(['c'], null))

    const response = await collectPaginatedOverview(fetchPage, {
      includeCategories: 'all',
      pageSize: 2,
    })

    expect(fetchPage).toHaveBeenCalledTimes(2)
    expect(fetchPage).toHaveBeenNthCalledWith(
      1,
      { includeCategories: 'all', page: 1, pageSize: 2 },
      undefined,
    )
    expect(fetchPage).toHaveBeenNthCalledWith(
      2,
      { includeCategories: 'all', page: 2, pageSize: 2 },
      undefined,
    )
    expect(response.results.map((row) => row.model.key)).toEqual(['a', 'b', 'c'])
    expect(response.count).toBe(3)
    expect(response.next).toBeNull()
  })

  it('forwards the abort signal to every page request', async () => {
    const controller = new AbortController()
    const fetchPage = vi.fn().mockResolvedValue(fakePage(['a'], null))

    await collectPaginatedOverview(fetchPage, {}, { signal: controller.signal })

    expect(fetchPage).toHaveBeenCalledWith(
      { page: 1, pageSize: 200 },
      { signal: controller.signal },
    )
  })

  it('throws rather than silently truncating when next never clears', async () => {
    const fetchPage = vi
      .fn()
      .mockResolvedValue(fakePage(['a'], 'https://example.test/overview/?page=2'))

    await expect(collectPaginatedOverview(fetchPage, { pageSize: 1 })).rejects.toThrow(
      /did not exhaust pagination/,
    )
    expect(fetchPage).toHaveBeenCalledTimes(OVERVIEW_PAGE_LIMIT)
  })
})
