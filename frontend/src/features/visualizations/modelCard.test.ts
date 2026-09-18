import { describe, expect, it } from 'vitest'

import {
  buildModelCardCatalog,
  formatPercentile,
  percentileAmong,
  type ModelCardSource,
} from './modelCard'

function source(
  key: string,
  input: Partial<Omit<ModelCardSource, 'key' | 'name' | 'organization'>> = {},
): ModelCardSource {
  return {
    agentic: input.agentic === undefined ? 40 : input.agentic,
    coding: input.coding === undefined ? 70 : input.coding,
    cost: input.cost === undefined ? 1 : input.cost,
    indexVersion: input.indexVersion === undefined ? 4.3 : input.indexVersion,
    intelligence: input.intelligence === undefined ? 30 : input.intelligence,
    key,
    name: key,
    organization: 'openai',
    speed: input.speed === undefined ? 80 : input.speed,
  }
}

describe('percentileAmong', () => {
  it('maps higher capability to a higher percentile', () => {
    expect(percentileAmong(10, [10, 20])).toBe(0.5)
    expect(percentileAmong(20, [10, 20])).toBe(1)
  })

  it('inverts cost so cheaper sits farther from the origin', () => {
    expect(percentileAmong(1, [1, 4], true)).toBe(1)
    expect(percentileAmong(4, [1, 4], true)).toBe(0.5)
  })
})

describe('buildModelCardCatalog', () => {
  it('keeps a null coding index as a gap instead of plotting zero', () => {
    const catalog = buildModelCardCatalog([
      source('full', { coding: 70, intelligence: 40 }),
      source('gap', { coding: null, intelligence: 30 }),
    ])
    const gap = catalog.cards.find((card) => card.key === 'gap')

    expect(gap?.axes.coding).toMatchObject({ raw: null, percentile: null })
    expect(gap?.measuredCount).toBe(4)
    expect(catalog.coverage.coding).toBe(1)
    expect(catalog.cards[0].key).toBe('full')
  })

  it('drops non-positive cost and speed instead of treating them as free or idle', () => {
    const catalog = buildModelCardCatalog([
      source('kept', { cost: 0.5, speed: 100 }),
      source('zero-cost', { cost: 0, speed: 100 }),
      source('null-speed', { cost: 0.5, speed: null }),
    ])
    const zeroCost = catalog.cards.find((card) => card.key === 'zero-cost')
    const nullSpeed = catalog.cards.find((card) => card.key === 'null-speed')

    expect(zeroCost?.axes.cost.percentile).toBeNull()
    expect(nullSpeed?.axes.speed.percentile).toBeNull()
    expect(catalog.coverage.cost).toBe(2)
    expect(catalog.coverage.speed).toBe(2)
  })

  it('features the strongest complete pentagon by default', () => {
    const catalog = buildModelCardCatalog([
      source('incomplete', { intelligence: 99, coding: null }),
      source('strong', { intelligence: 50 }),
      source('weaker', { intelligence: 20 }),
    ])

    expect(catalog.defaultKey).toBe('strong')
    expect(catalog.indexVersion).toBe(4.3)
  })
})

describe('formatPercentile', () => {
  it('uses ordinals for the inspector', () => {
    expect(formatPercentile(1)).toBe('100th')
    expect(formatPercentile(0.5)).toBe('50th')
    expect(formatPercentile(null)).toBe('Not measured')
  })
})
