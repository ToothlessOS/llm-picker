import { QueryClient } from '@tanstack/react-query'

import { ApiError, isAbortError } from '../api'

function shouldRetry(failureCount: number, error: unknown): boolean {
  if (isAbortError(error)) return false
  if (error instanceof ApiError && error.status < 500) return false
  return failureCount < 2
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 10 * 60 * 1_000,
        refetchOnWindowFocus: false,
        retry: shouldRetry,
        retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 5_000),
        staleTime: 60_000,
      },
    },
  })
}

export const queryClient = createQueryClient()
