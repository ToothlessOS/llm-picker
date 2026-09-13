const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000/api/v1/leaderboard/'

export function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim()
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`
}

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim()

export const API_BASE_URL = normalizeApiBaseUrl(
  configuredBaseUrl || DEFAULT_API_BASE_URL,
)

export { DEFAULT_API_BASE_URL }
