import { describe, expect, it } from 'vitest'

import { createApiClient } from './client'
import {
  ApiDecodeError,
  ApiError,
  ApiNetworkError,
  isAbortError,
  isModelIncompleteErrorBody,
} from './errors'

describe('API client', () => {
  it('builds a GET request with query parameters and a signal', async () => {
    let requestedUrl = ''
    let requestedInit: RequestInit | undefined
    const fetchImpl: typeof fetch = async (input, init) => {
      requestedUrl = input.toString()
      requestedInit = init
      return Response.json({ results: [] })
    }
    const controller = new AbortController()
    const client = createApiClient({
      baseUrl: 'https://example.test/api/v1/leaderboard',
      fetchImpl,
    })

    await client.get('overview/', { search: 'Claude', page_size: 25 }, {
      signal: controller.signal,
    })

    expect(requestedUrl).toBe(
      'https://example.test/api/v1/leaderboard/overview/?search=Claude&page_size=25',
    )
    expect(requestedInit?.method).toBe('GET')
    expect(requestedInit?.signal).toBe(controller.signal)
    expect(requestedInit?.headers).toEqual({ Accept: 'application/json' })
  })

  it('preserves the backend structured error body', async () => {
    const body = {
      error: 'model_incomplete',
      model_key: 'missing-model',
      reason: 'no_aa_match',
      message: 'The model has no AA counterpart.',
    }
    const client = createApiClient({
      fetchImpl: async () => Response.json(body, { status: 404 }),
    })

    const error = await client.get('models/missing-model/').catch((value) => value)

    expect(error).toBeInstanceOf(ApiError)
    if (!(error instanceof ApiError)) throw error
    expect(error.status).toBe(404)
    expect(isModelIncompleteErrorBody(error.body)).toBe(true)
    expect(error.body).toEqual(body)
  })

  it('reports successful responses that are not valid JSON', async () => {
    const client = createApiClient({
      fetchImpl: async () => new Response('not-json', { status: 200 }),
    })

    await expect(client.get('overview/')).rejects.toBeInstanceOf(ApiDecodeError)
  })

  it('keeps the HTTP status when an error response is not JSON', async () => {
    const client = createApiClient({
      fetchImpl: async () => new Response('Service unavailable', { status: 503 }),
    })

    const error = await client.get('overview/').catch((value) => value)

    expect(error).toBeInstanceOf(ApiError)
    if (!(error instanceof ApiError)) throw error
    expect(error.status).toBe(503)
    expect(error.body).toBe('Service unavailable')
  })

  it('wraps network failures with the requested URL', async () => {
    const client = createApiClient({
      baseUrl: 'https://example.test/api/',
      fetchImpl: async () => {
        throw new TypeError('offline')
      },
    })

    const error = await client.get('metadata/').catch((value) => value)

    expect(error).toBeInstanceOf(ApiNetworkError)
    if (!(error instanceof ApiNetworkError)) throw error
    expect(error.url).toBe('https://example.test/api/metadata/')
  })

  it('passes AbortError through without turning it into a network error', async () => {
    const fetchImpl: typeof fetch = (_input, init) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'))
        })
      })
    const controller = new AbortController()
    const client = createApiClient({ fetchImpl })

    const request = client.get('overview/', {}, { signal: controller.signal })
    controller.abort()
    const error = await request.catch((value) => value)

    expect(isAbortError(error)).toBe(true)
    expect(error).not.toBeInstanceOf(ApiNetworkError)
  })
})
