import { API_BASE_URL, normalizeApiBaseUrl } from './config'
import {
  ApiDecodeError,
  ApiError,
  ApiNetworkError,
  isAbortError,
} from './errors'
import { buildQueryString, type QueryParams } from './query'

export interface ApiRequestOptions {
  signal?: AbortSignal
}

export interface ApiClient {
  get<T>(
    path: string,
    query?: QueryParams,
    options?: ApiRequestOptions,
  ): Promise<T>
}

export interface CreateApiClientOptions {
  baseUrl?: string
  fetchImpl?: typeof fetch
}

async function decodeJson(response: Response, url: string): Promise<unknown> {
  const rawBody = await response.text()
  if (rawBody === '') return null

  try {
    return JSON.parse(rawBody) as unknown
  } catch (error) {
    if (!response.ok) return rawBody
    throw new ApiDecodeError(response.status, url, error)
  }
}

export function createApiClient({
  baseUrl = API_BASE_URL,
  fetchImpl = globalThis.fetch.bind(globalThis),
}: CreateApiClientOptions = {}): ApiClient {
  const normalizedBaseUrl = normalizeApiBaseUrl(baseUrl)

  return {
    async get<T>(
      path: string,
      query: QueryParams = {},
      options: ApiRequestOptions = {},
    ): Promise<T> {
      const relativePath = path.replace(/^\/+/, '')
      const url = new URL(relativePath, normalizedBaseUrl)
      const queryString = buildQueryString(query)
      if (queryString) url.search = queryString

      let response: Response
      try {
        response = await fetchImpl(url, {
          headers: { Accept: 'application/json' },
          method: 'GET',
          signal: options.signal,
        })
      } catch (error) {
        if (isAbortError(error)) throw error
        throw new ApiNetworkError(url.toString(), error)
      }

      const body = await decodeJson(response, url.toString())
      if (!response.ok) {
        throw new ApiError(response.status, body, url.toString())
      }

      return body as T
    },
  }
}

export const apiClient = createApiClient()
