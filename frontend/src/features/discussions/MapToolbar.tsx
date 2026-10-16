import { X } from 'lucide-react'

import type { DiscussionEntity } from '../../api'
import { formatNumber } from '../../app/format'
import { MAX_DISCUSSION_FILTERS } from '../../app/useDiscussionFilters'
import {
  DEPTH_OPTIONS,
  type DiscussionMapState,
} from '../../app/useDiscussionMapState'
import type { DepthMode } from './discussionTree'
import { SearchField } from '../../components/SearchField'

export interface MapSummary {
  posts: number
  roots: number
  matchTotal: number
  visible: number
  /** What the match count counts — an entity's label, or "your search". */
  matchLabel: string | null
}

export interface MapToolbarProps {
  entities: DiscussionEntity[]
  state: DiscussionMapState
  summary: MapSummary | null
  onSearch: (value: string) => void
  onToggleEntity: (slug: string) => void
  onDepth: (value: DepthMode | 'auto') => void
  onHideQuiet: (value: boolean) => void
  onClear: () => void
}

/**
 * The search and filter bar.
 *
 * The two dropdowns are the axes the feature was specified with — a provider and
 * a service — but they write to **one** `entity` param, because the endpoint
 * rolls a service up to its vendor there and a single vocabulary is what makes
 * `?entity=anthropic` mean "Anthropic and everything it ships". A select *adds* a
 * filter rather than replacing one; the chips are where the active set lives and
 * where it is removed.
 */
export function MapToolbar({
  entities,
  state,
  summary,
  onSearch,
  onToggleEntity,
  onDepth,
  onHideQuiet,
  onClear,
}: MapToolbarProps) {
  const vendors = entities.filter((entity) => entity.kind === 'vendor')
  const services = entities.filter((entity) => entity.kind === 'service')
  const active = new Map(entities.map((entity) => [entity.slug, entity]))
  const atCap = state.entities.length >= MAX_DISCUSSION_FILTERS
  const hasQuery = state.search !== '' || state.entities.length > 0

  return (
    <div className="filter-band filter-band--inline map-toolbar" aria-label="Map controls">
      <div className="filter-band__inner">
        <SearchField
          label="Search this thread"
          onSearchChange={onSearch}
          placeholder="Words in any comment"
          value={state.search}
        />

        <label className="filter-control">
          <span className="filter-control__label">Provider</span>
          <select
            aria-describedby={atCap ? 'map-filter-cap' : undefined}
            disabled={atCap}
            onChange={(event) => {
              if (event.target.value) onToggleEntity(event.target.value)
              event.target.value = ''
            }}
            value=""
          >
            <option value="">Add a provider…</option>
            {vendors.map((entity) => (
              <option key={entity.slug} value={entity.slug}>
                {entity.label} ({formatNumber(entity.thread_count, 0)})
              </option>
            ))}
          </select>
        </label>

        <label className="filter-control">
          <span className="filter-control__label">Service</span>
          <select
            aria-describedby={atCap ? 'map-filter-cap' : undefined}
            disabled={atCap}
            onChange={(event) => {
              if (event.target.value) onToggleEntity(event.target.value)
              event.target.value = ''
            }}
            value=""
          >
            <option value="">Add a service…</option>
            {services.map((entity) => (
              <option key={entity.slug} value={entity.slug}>
                {entity.label} ({formatNumber(entity.thread_count, 0)})
              </option>
            ))}
          </select>
        </label>

        <label className="filter-control">
          <span className="filter-control__label">Depth</span>
          <select
            onChange={(event) => onDepth(event.target.value as DepthMode | 'auto')}
            value={state.depth ?? 'auto'}
          >
            {DEPTH_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button
          className="filter-clear"
          disabled={!hasQuery}
          onClick={onClear}
          type="button"
        >
          Clear
        </button>
      </div>

      <div className="map-toolbar__row">
        {state.entities.length > 0 ? (
          <ul className="map-chips" aria-label="Active filters">
            {state.entities.map((slug) => (
              <li key={slug}>
                <button
                  className="map-chip"
                  onClick={() => onToggleEntity(slug)}
                  type="button"
                >
                  {active.get(slug)?.label ?? slug}
                  <X aria-hidden="true" size={13} />
                  <span className="sr-only">Remove this filter</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {hasQuery ? (
          <label className="map-toolbar__checkbox">
            <input
              checked={state.hideQuiet}
              onChange={(event) => onHideQuiet(event.target.checked)}
              type="checkbox"
            />
            Hide branches with no match
          </label>
        ) : null}

        {summary ? (
          <p className="map-toolbar__counts" role="status">
            {formatNumber(summary.posts, 0)} posts ·{' '}
            {formatNumber(summary.roots, 0)} top-level
            {summary.matchLabel !== null
              ? ` · ${formatNumber(summary.matchTotal, 0)} match ${summary.matchLabel}`
              : ''}{' '}
            · {formatNumber(summary.visible, 0)} rows shown
          </p>
        ) : (
          <p className="map-toolbar__counts muted" role="status">
            Pick a thread to map.
          </p>
        )}
      </div>

      {atCap ? (
        <p className="map-toolbar__note" id="map-filter-cap">
          {MAX_DISCUSSION_FILTERS} filters is the most the colour legend can tell
          apart. Remove one to add another.
        </p>
      ) : null}
    </div>
  )
}
