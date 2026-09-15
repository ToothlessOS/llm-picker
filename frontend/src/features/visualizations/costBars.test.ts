import { describe, expect, it } from 'vitest'

import {
  buildCostBarModel,
  formatBarAxisCurrency,
  type CostBarSource,
} from './costBars'

function source(
  key: string,
  cost: number | null,
  prices: {
    input?: number | null
    output?: number | null
    cacheHit?: number | null
    cacheWrite?: number | null
  } = {},
): CostBarSource {
  return {
    key,
    name: key,
    organization: 'openai',
    cost,
    input: prices.input ?? null,
    output: prices.output ?? null,
    cacheHit: prices.cacheHit ?? null,
    cacheWrite: prices.cacheWrite ?? null,
  }
}

describe('buildCostBarModel', () => {
  it('drops null and non-positive costs instead of drawing a free task', () => {
    const model = buildCostBarModel([
      source('kept', 0.4, { input: 1, output: 3 }),
      source('null-cost', null, { input: 1, output: 3 }),
      source('zero', 0, { input: 1, output: 3 }),
    ])

    expect(model.bars.map((bar) => bar.key)).toEqual(['kept'])
    expect(model.omitted).toBe(2)
  })

  it('attributes task cost by measured list-price mix and skips null prices', () => {
    const model = buildCostBarModel([
      source('mixed', 1, { input: 1, output: 3, cacheHit: 0, cacheWrite: null }),
    ])
    const bar = model.bars[0]
    const byId = Object.fromEntries(bar.segments.map((segment) => [segment.id, segment]))

    expect(bar.segments.map((segment) => segment.id)).toEqual([
      'input',
      'output',
      'cacheHit',
    ])
    expect(byId.input.value).toBeCloseTo(0.25)
    expect(byId.output.value).toBeCloseTo(0.75)
    expect(byId.cacheHit.value).toBe(0)
    expect(byId.cacheWrite).toBeUndefined()
  })

  it('keeps the whole bar unspecified when no priced mix can be formed', () => {
    const model = buildCostBarModel([source('bare', 0.8)])

    expect(model.bars[0].segments).toEqual([
      { id: 'unspecified', label: 'Unspecified', price: null, value: 0.8 },
    ])
  })

  it('sorts cheapest task first', () => {
    const model = buildCostBarModel([
      source('dear', 2, { input: 1, output: 1 }),
      source('cheap', 0.2, { input: 1, output: 1 }),
    ])

    expect(model.bars.map((bar) => bar.key)).toEqual(['cheap', 'dear'])
    expect(model.medianCost).toBe(1.1)
  })
})

describe('formatBarAxisCurrency', () => {
  it('keeps fractional dollars instead of rounding them into duplicate ticks', () => {
    expect(formatBarAxisCurrency(1.5)).not.toBe(formatBarAxisCurrency(1))
    expect(formatBarAxisCurrency(1.5)).not.toBe(formatBarAxisCurrency(2))
    expect(formatBarAxisCurrency(0.5)).toMatch(/0[.,]50/)
  })
})
