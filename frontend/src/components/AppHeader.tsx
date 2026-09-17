import {
  BarChart3,
  Boxes,
  DatabaseZap,
  Gauge,
  type LucideIcon,
} from 'lucide-react'
import { NavLink, useLocation } from 'react-router-dom'

import {
  getFreshnessState,
  type FreshnessState,
  type MetadataResponse,
} from '../api'
import { formatDateTime } from '../app/format'
import { ThemeToggle } from './ThemeToggle'

interface NavigationItem {
  label: string
  path: string
  icon: LucideIcon
  end?: boolean
}

const dataNavigation: NavigationItem[] = [
  { label: 'Models', path: '/models', icon: Gauge },
  { label: 'Categories', path: '/categories', icon: BarChart3 },
  { label: 'AA Models', path: '/artificial-analysis', icon: Boxes },
  { label: 'Data Quality', path: '/data-quality', icon: DatabaseZap },
]

const freshnessPriority: FreshnessState[] = [
  'refresh_failed',
  'never_refreshed',
  'stale',
  'not_configured',
  'fresh',
]

function summarizeFreshness(metadata: MetadataResponse | undefined) {
  if (!metadata) return { label: 'Checking data', state: 'loading', updatedAt: null }

  const sourceStates = Object.values(metadata.sources).map(getFreshnessState)
  const state =
    freshnessPriority.find((candidate) => sourceStates.includes(candidate)) ??
    'fresh'
  const labels: Record<FreshnessState, string> = {
    fresh: 'Data current',
    never_refreshed: 'Awaiting data',
    not_configured: 'Source unavailable',
    refresh_failed: 'Refresh issue',
    stale: 'Data stale',
  }
  const timestamps = Object.values(metadata.sources)
    .map((source) => source.last_success_at)
    .filter((value): value is string => value !== null)
    .sort()

  return {
    label: labels[state],
    state,
    updatedAt: timestamps[0] ?? null,
  }
}

interface AppHeaderProps {
  metadata?: MetadataResponse
}

export function AppHeader({ metadata }: AppHeaderProps) {
  const location = useLocation()
  const freshness = summarizeFreshness(metadata)
  const isHome = location.pathname === '/'
  const search = location.search

  return (
    <header className="app-header">
      <div className={`app-header__inner${isHome ? '' : ' app-header__inner--bar'}`}>
        <NavLink
          aria-label={isHome ? 'LLM Picker' : 'Click me to return'}
          className={isHome ? 'brand' : 'brand brand--return'}
          end
          to={{ pathname: '/', search }}
        >
          <span className="brand__name">LLM Picker</span>
          {isHome ? null : (
            <span className="brand__hint">click me to return</span>
          )}
        </NavLink>

        <div className="header-actions">
          {isHome ? (
            <nav className="primary-nav" aria-label="Primary navigation">
              <NavLink
                className={({ isActive }) =>
                  `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`
                }
                to={{ pathname: '/models', search }}
              >
                Models
              </NavLink>
            </nav>
          ) : (
            <nav className="primary-nav primary-nav--bar" aria-label="Data pages">
              {dataNavigation.map(({ label, path, icon: Icon, end }) => (
                <NavLink
                  className={({ isActive }) =>
                    `primary-nav__link${isActive ? ' primary-nav__link--active' : ''}`
                  }
                  end={end}
                  key={path}
                  to={{ pathname: path, search }}
                >
                  <Icon aria-hidden="true" size={17} strokeWidth={1.8} />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>
          )}

          <NavLink
            className={`freshness-indicator freshness-indicator--${freshness.state}`}
            title={
              freshness.updatedAt
                ? `Oldest source updated ${formatDateTime(freshness.updatedAt)}`
                : freshness.label
            }
            to={{ pathname: '/data-quality', search }}
          >
            <span className="freshness-indicator__dot" aria-hidden="true" />
            <span>{freshness.label}</span>
          </NavLink>

          {isHome ? <ThemeToggle /> : null}
        </div>
      </div>
    </header>
  )
}
