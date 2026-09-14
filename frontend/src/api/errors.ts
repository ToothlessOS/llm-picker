export type KnownApiErrorCode =
  | 'invalid_parameter'
  | 'invalid_request'
  | 'method_not_allowed'
  | 'model_incomplete'
  | 'not_found'
  | 'server_error'
  | 'unknown_value'

export interface ApiErrorBody {
  error: KnownApiErrorCode | (string & {})
  message?: string
  detail?: unknown
  param?: string
  allowed?: string[]
  model_key?: string
  reason?: string
  [key: string]: unknown
}

export interface ModelIncompleteErrorBody extends ApiErrorBody {
  error: 'model_incomplete'
  model_key: string
  reason: string
  message: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return isRecord(value) && typeof value.error === 'string'
}

export function isModelIncompleteErrorBody(
  value: unknown,
): value is ModelIncompleteErrorBody {
  return (
    isApiErrorBody(value) &&
    value.error === 'model_incomplete' &&
    typeof value.model_key === 'string' &&
    typeof value.reason === 'string' &&
    typeof value.message === 'string'
  )
}

function messageFromBody(body: unknown, fallback: string): string {
  if (!isRecord(body)) return fallback
  if (typeof body.message === 'string') return body.message
  if (typeof body.detail === 'string') return body.detail
  return fallback
}

export class ApiError extends Error {
  readonly body: unknown
  readonly status: number
  readonly url: string

  constructor(status: number, body: unknown, url: string) {
    super(messageFromBody(body, `API request failed with status ${status}.`))
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.url = url
  }
}

export class ApiNetworkError extends Error {
  readonly cause: unknown
  readonly url: string

  constructor(url: string, cause: unknown) {
    super('Unable to reach the API.')
    this.name = 'ApiNetworkError'
    this.url = url
    this.cause = cause
  }
}

export class ApiDecodeError extends Error {
  readonly cause: unknown
  readonly status: number
  readonly url: string

  constructor(status: number, url: string, cause: unknown) {
    super('The API returned a response that was not valid JSON.')
    this.name = 'ApiDecodeError'
    this.status = status
    this.url = url
    this.cause = cause
  }
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === 'AbortError') ||
    (isRecord(error) && error.name === 'AbortError')
  )
}
