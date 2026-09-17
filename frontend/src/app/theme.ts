export type Theme = 'day' | 'night'
export type ThemePreference = Theme | 'auto'

const DAY_START_HOUR = 6
const NIGHT_START_HOUR = 18

export function themeFromLocalTime(date: Date = new Date()): Theme {
  const hour = date.getHours()
  return hour >= DAY_START_HOUR && hour < NIGHT_START_HOUR ? 'day' : 'night'
}

export function msUntilNextThemeBoundary(date: Date = new Date()): number {
  const next = new Date(date)
  next.setSeconds(0, 0)
  const hour = date.getHours()
  if (hour >= DAY_START_HOUR && hour < NIGHT_START_HOUR) {
    next.setHours(NIGHT_START_HOUR, 0, 0, 0)
  } else if (hour < DAY_START_HOUR) {
    next.setHours(DAY_START_HOUR, 0, 0, 0)
  } else {
    next.setDate(next.getDate() + 1)
    next.setHours(DAY_START_HOUR, 0, 0, 0)
  }
  return Math.max(next.getTime() - date.getTime(), 1000)
}

export function themeFromSearch(search: string): Theme | null {
  const value = new URLSearchParams(search).get('theme')
  return value === 'day' || value === 'night' ? value : null
}

export function preferenceFromSearch(search: string): ThemePreference {
  return themeFromSearch(search) ?? 'auto'
}

export function searchWithThemePreference(
  search: string,
  preference: ThemePreference,
): string {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  if (preference === 'auto') {
    params.delete('theme')
  } else {
    params.set('theme', preference)
  }
  const next = params.toString()
  return next ? `?${next}` : ''
}

export function resolveTheme(
  search: string = window.location.search,
  date: Date = new Date(),
): Theme {
  return themeFromSearch(search) ?? themeFromLocalTime(date)
}

export function applyTheme(
  theme: Theme,
  root: HTMLElement = document.documentElement,
) {
  root.dataset.theme = theme
}

let timer = 0
let visibilityBound = false

export function stopThemeClock() {
  window.clearTimeout(timer)
  timer = 0
}

function onVisibilityChange() {
  if (document.hidden || themeFromSearch(window.location.search)) return
  applyTheme(themeFromLocalTime())
  scheduleThemeClock()
}

function bindVisibility() {
  if (visibilityBound) return
  visibilityBound = true
  document.addEventListener('visibilitychange', onVisibilityChange)
}

function scheduleThemeClock() {
  window.clearTimeout(timer)
  timer = window.setTimeout(() => {
    applyTheme(themeFromLocalTime())
    scheduleThemeClock()
  }, msUntilNextThemeBoundary())
}

export function syncThemeFromSearch(search: string = window.location.search) {
  bindVisibility()
  const override = themeFromSearch(search)
  if (override) {
    stopThemeClock()
    applyTheme(override)
    return
  }

  applyTheme(themeFromLocalTime())
  scheduleThemeClock()
}

export function startThemeClock() {
  syncThemeFromSearch(window.location.search)
}
