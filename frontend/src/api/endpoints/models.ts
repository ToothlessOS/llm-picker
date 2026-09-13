import { apiClient, type ApiRequestOptions } from '../client'
import type { ModelDetailResponse } from '../types/models'

export function getModel(
  key: string,
  options?: ApiRequestOptions,
): Promise<ModelDetailResponse> {
  return apiClient.get(`models/${encodeURIComponent(key)}/`, {}, options)
}
