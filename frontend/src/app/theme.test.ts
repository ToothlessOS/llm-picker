import { describe, expect, it } from 'vitest'

import { msUntilNextThemeBoundary, themeFromLocalTime, themeFromSearch } from './theme'

function at(hours: number, minutes = 0) {
  return new Date(2026, 8, 15, hours, minutes, 0, 0)
}

describe('themeFromLocalTime', () => {
  it('uses the day theme from 6:00 until 18:00', () => {
    expect(themeFromLocalTime(at(6))).toBe('day')
    expect(themeFromLocalTime(at(12))).toBe('day')
    expect(themeFromLocalTime(at(17, 59))).toBe('day')
  })

  it('uses the night theme otherwise', () => {
    expect(themeFromLocalTime(at(18))).toBe('night')
    expect(themeFromLocalTime(at(23, 30))).toBe('night')
    expect(themeFromLocalTime(at(0))).toBe('night')
    expect(themeFromLocalTime(at(5, 59))).toBe('night')
  })
})

describe('themeFromSearch', () => {
  it('reads an explicit theme from the query string', () => {
    expect(themeFromSearch('?theme=night')).toBe('night')
    expect(themeFromSearch('?theme=day')).toBe('day')
    expect(themeFromSearch('?theme=sepia')).toBeNull()
    expect(themeFromSearch('')).toBeNull()
  })
})

describe('msUntilNextThemeBoundary', () => {
  it('waits until 18:00 during the day', () => {
    expect(msUntilNextThemeBoundary(at(10))).toBe(8 * 60 * 60 * 1000)
  })

  it('waits until 6:00 after 18:00', () => {
    expect(msUntilNextThemeBoundary(at(20))).toBe(10 * 60 * 60 * 1000)
  })

  it('waits until 6:00 before dawn', () => {
    expect(msUntilNextThemeBoundary(at(2))).toBe(4 * 60 * 60 * 1000)
  })
})
