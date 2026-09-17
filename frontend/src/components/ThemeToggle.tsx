import { Moon, Sun } from 'lucide-react'
import { useNavigate, useLocation } from 'react-router-dom'

import {
  preferenceFromSearch,
  resolveTheme,
  searchWithThemePreference,
  syncThemeFromSearch,
  type ThemePreference,
} from '../app/theme'

const options = [
  { value: 'day', label: 'Day theme' },
  { value: 'night', label: 'Night theme' },
  { value: 'auto', label: 'Auto theme' },
] as const

export function ThemeToggle() {
  const location = useLocation()
  const navigate = useNavigate()
  const preference = preferenceFromSearch(location.search)
  const resolved = resolveTheme(location.search)

  function selectPreference(next: ThemePreference) {
    if (next === preference) return
    const search = searchWithThemePreference(location.search, next)
    syncThemeFromSearch(search)
    navigate(
      {
        pathname: location.pathname,
        search,
        hash: location.hash,
      },
      { replace: true },
    )
  }

  return (
    <div
      aria-label="Theme"
      className="theme-toggle"
      data-theme-mode={preference}
      data-theme-resolved={resolved}
      role="radiogroup"
    >
      <span aria-hidden="true" className="theme-toggle__thumb" />
      {options.map((option) => (
        <button
          aria-checked={preference === option.value}
          aria-label={option.label}
          className="theme-toggle__option"
          key={option.value}
          onClick={() => selectPreference(option.value)}
          role="radio"
          title={
            option.value === 'auto'
              ? 'Auto: day from 6:00 to 18:00'
              : option.label
          }
          type="button"
        >
          {option.value === 'day' ? (
            <Sun aria-hidden="true" size={15} strokeWidth={1.8} />
          ) : null}
          {option.value === 'night' ? (
            <Moon aria-hidden="true" size={15} strokeWidth={1.8} />
          ) : null}
          {option.value === 'auto' ? <span>Auto</span> : null}
        </button>
      ))}
    </div>
  )
}
