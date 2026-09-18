import { describe, expect, it } from 'vitest'

import {
  msUntilNextThemeBoundary,
  preferenceFromSearch,
  searchWithThemePreference,
  themeFromLocalTime,
  themeFromSearch,
} from './theme'

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

describe('preferenceFromSearch', () => {
  it('treats a missing or unknown theme as auto', () => {
    expect(preferenceFromSearch('')).toBe('auto')
    expect(preferenceFromSearch('?q=gpt')).toBe('auto')
    expect(preferenceFromSearch('?theme=sepia')).toBe('auto')
  })

  it('reads an explicit day or night preference', () => {
    expect(preferenceFromSearch('?theme=day')).toBe('day')
    expect(preferenceFromSearch('?theme=night')).toBe('night')
  })
})

describe('searchWithThemePreference', () => {
  it('writes an explicit theme into the query string', () => {
    expect(searchWithThemePreference('', 'night')).toBe('?theme=night')
    expect(searchWithThemePreference('?q=gpt', 'day')).toBe('?q=gpt&theme=day')
  })

  it('removes the theme param in auto mode', () => {
    expect(searchWithThemePreference('?theme=night', 'auto')).toBe('')
    expect(searchWithThemePreference('?q=gpt&theme=day', 'auto')).toBe('?q=gpt')
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
