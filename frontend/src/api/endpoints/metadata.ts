import { apiClient, type ApiRequestOptions } from '../client'
import type { MetadataResponse } from '../types/metadata'

export function getMetadata(
  options?: ApiRequestOptions,
): Promise<MetadataResponse> {
  return apiClient.get('metadata/', {}, options)
}
