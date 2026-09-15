import { AlertCircle, RefreshCw } from 'lucide-react'

import {
  ApiDecodeError,
  ApiError,
  ApiNetworkError,
  isApiErrorBody,
  isModelIncompleteErrorBody,
} from '../../api'

function errorCopy(error: unknown): { title: string; message: string } {
  if (error instanceof ApiNetworkError) {
    return {
      title: 'Backend unavailable',
      message: 'The application could not reach the leaderboard API.',
    }
  }
  if (error instanceof ApiDecodeError) {
    return {
      title: 'Unexpected response',
      message: 'The API returned data in an unreadable format.',
    }
  }
  if (error instanceof ApiError) {
    if (isModelIncompleteErrorBody(error.body)) {
      return { title: 'Model data is incomplete', message: error.body.message }
    }
    if (isApiErrorBody(error.body)) {
      if (error.body.error === 'throttled' || error.status === 429) {
        return {
          title: 'Too many requests',
          message: error.body.message ?? 'Please wait briefly before trying again.',
        }
      }
      return {
        title: error.body.error === 'invalid_parameter' ? 'Check the filters' : 'Request failed',
        message: error.body.message ?? error.message,
      }
    }
    return { title: 'Request failed', message: error.message }
  }
  return { title: 'Something went wrong', message: 'Please try the request again.' }
}

interface ErrorStateProps {
  error: unknown
  onRetry?: () => void
}

export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const copy = errorCopy(error)

  return (
    <div className="state-message state-message--error" role="alert">
      <AlertCircle aria-hidden="true" size={28} strokeWidth={1.6} />
      <h2>{copy.title}</h2>
      <p>{copy.message}</p>
      {onRetry ? (
        <button className="button button--secondary" onClick={onRetry} type="button">
          <RefreshCw aria-hidden="true" size={16} />
          Retry
        </button>
      ) : null}
    </div>
  )
}
