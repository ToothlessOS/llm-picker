import { describe, expect, it } from 'vitest'

import {
  getFreshnessState,
  getSourceDataUpdatedAt,
  type ResponseMeta,
  type SourceFreshnessBase,
} from './types/common'

function freshness(
  overrides: Partial<SourceFreshnessBase> = {},
): SourceFreshnessBase {
  return {
    configured: true,
    last_attempt_at: '2026-09-13T00:00:00Z',
    last_status: 'success',
    last_success_at: '2026-09-13T00:00:00Z',
    age_seconds: 60,
    is_stale: false,
    stale_after_seconds: 50_400,
    last_error: null,
    ...overrides,
  }
}

describe('freshness helpers', () => {
  it.each([
    [{ configured: false }, 'not_configured'],
    [{ last_success_at: null }, 'never_refreshed'],
    [{ last_status: 'failed' }, 'refresh_failed'],
    [{ is_stale: true }, 'stale'],
    [{}, 'fresh'],
  ] as const)('maps %o to %s', (overrides, expected) => {
    expect(getFreshnessState(freshness(overrides))).toBe(expected)
  })

  it('treats a partial refresh as successful freshness-wise', () => {
    expect(getFreshnessState(freshness({ last_status: 'partial' }))).toBe(
      'fresh',
    )
  })

  it('returns the selected source update time', () => {
    const meta: ResponseMeta = {
      generated_at: '2026-09-13T01:00:00Z',
      sources: {
        lmarena: freshness({ last_success_at: '2026-09-12T23:00:00Z' }),
        artificial_analysis: freshness({
          last_success_at: '2026-09-13T00:00:00Z',
        }),
      },
    }

    expect(getSourceDataUpdatedAt(meta, 'lmarena')).toBe(
      '2026-09-12T23:00:00Z',
    )
  })
})
