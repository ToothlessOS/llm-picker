import { describe, expect, it } from 'vitest'

import {
  buildScatterModel,
  formatAxisCurrency,
  providerColor,
  providerLabel,
  type ScatterSource,
} from './scatter'

function source(
  key: string,
  name: string,
  cost: number | null,
  intelligence: number | null,
  organization: string | null = 'openai',
): ScatterSource {
  return { key, name, organization, intelligence, cost }
}

describe('buildScatterModel', () => {
  it('drops null and non-positive costs instead of plotting them at the origin', () => {
    const model = buildScatterModel([
      source('kept', 'Kept', 0.2, 40),
      source('null-cost', 'Null cost', null, 50),
      source('null-intel', 'Null intel', 0.1, null),
      source('free', 'Zero cost', 0, 60),
    ])

    expect(model.points.map((point) => point.key)).toEqual(['kept'])
    expect(model.omitted).toBe(3)
  })

  it('marks the cost-intelligence Pareto front', () => {
    const model = buildScatterModel([
      source('cheap-weak', 'Cheap weak', 0.5, 8, 'xiaomi'),
      source('cheap-mid', 'Cheap mid', 1, 10, 'openai'),
      source('expensive-strong', 'Expensive strong', 2, 20, 'anthropic'),
      source('expensive-weak', 'Expensive weak', 2, 5, 'google'),
    ])

    expect(model.pareto.map((point) => point.key)).toEqual([
      'cheap-weak',
      'cheap-mid',
      'expensive-strong',
    ])
    expect(model.points.find((point) => point.key === 'expensive-weak')?.onPareto).toBe(
      false,
    )
  })

  it('uses strict medians for the most attractive quadrant', () => {
    const model = buildScatterModel([
      source('a', 'A', 1, 10),
      source('b', 'B', 2, 30),
      source('c', 'C', 3, 20),
      source('d', 'D', 4, 40),
    ])

    expect(model.medianCost).toBe(2.5)
    expect(model.medianIntelligence).toBe(25)
    expect(model.points.find((point) => point.key === 'b')?.inAttractiveQuadrant).toBe(
      true,
    )
    expect(model.points.find((point) => point.key === 'a')?.inAttractiveQuadrant).toBe(
      false,
    )
    expect(model.points.find((point) => point.key === 'd')?.inAttractiveQuadrant).toBe(
      false,
    )
  })
})

describe('provider labels and colors', () => {
  it('uses canonical names for known providers', () => {
    expect(providerLabel('openai')).toBe('OpenAI')
    expect(providerLabel('xai')).toBe('xAI')
    expect(providerLabel(null)).toBe('Unknown')
  })

  it('assigns stable colors from a sorted provider list', () => {
    expect(providerColor('openai', ['anthropic', 'openai'])).toBe(
      providerColor('openai', ['openai', 'anthropic']),
    )
    expect(providerColor('anthropic', ['anthropic', 'openai'])).not.toBe(
      providerColor('openai', ['anthropic', 'openai']),
    )
  })
})

describe('formatAxisCurrency', () => {
  it('keeps cents below a dollar and drops them at or above it', () => {
    expect(formatAxisCurrency(0.05)).toMatch(/0[.,]05/)
    expect(formatAxisCurrency(1)).not.toMatch(/[.,]00/)
  })
})
