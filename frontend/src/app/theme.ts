export type Theme = 'day' | 'night'

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

export function startThemeClock() {
  const override = themeFromSearch(window.location.search)
  if (override) {
    applyTheme(override)
    return
  }

  let timer = 0

  const sync = () => applyTheme(themeFromLocalTime())
  const schedule = () => {
    window.clearTimeout(timer)
    timer = window.setTimeout(() => {
      sync()
      schedule()
    }, msUntilNextThemeBoundary())
  }

  sync()
  schedule()
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
      sync()
      schedule()
    }
  })
}
