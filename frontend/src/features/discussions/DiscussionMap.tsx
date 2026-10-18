import { useEffect, useMemo, useRef, useState } from 'react'

import { formatNumber } from '../../app/format'
import {
  windowRows,
  type MapLayout,
  type MapRow,
} from './discussionTree'

export interface DiscussionMapProps {
  layout: MapLayout
  /**
   * The row the map should point at and keep in view, already resolved to
   * something that is actually drawn — see `nearestDrawnRow`. The page resolves
   * it because only the page has the tree.
   */
  activeId: number | null
  onFocus: (id: number) => void
  onToggle: (id: number) => void
  onGeometry: (width: number, height: number) => void
}

/**
 * How close to an edge the active row may drift before the map moves, as a
 * fraction of the pane and then capped.
 *
 * A comfort band rather than exact centring on every change: the map is a
 * context view, and one that re-centred itself continuously would be in constant
 * motion beside a reader who is scrolling. Outside the band it centres the row,
 * so the map advances in steps and then holds still.
 */
const FOLLOW_MARGIN_RATIO = 0.3
const FOLLOW_MARGIN_MAX = 140

/**
 * A block's fill: one hue per entity mentioned, as equal vertical bands.
 *
 * Bands rather than a blend, because two hues mixed make a third colour that
 * means nothing — and rather than a grid, because bands scale with the block's
 * *width* and so stay legible on a 14px-tall row where a 2×2 grid would be
 * sub-pixel slivers.
 */
function bands(hues: readonly string[]): string | undefined {
  if (hues.length === 0) return undefined
  if (hues.length === 1) return hues[0]

  const step = 100 / hues.length
  const stops = hues.map(
    (hue, index) => `${hue} ${index * step}% ${(index + 1) * step}%`,
  )
  return `linear-gradient(90deg, ${stops.join(', ')})`
}

function summaryLabel(row: MapRow): string {
  const replies = `${formatNumber(row.hiddenCount, 0)} repl${row.hiddenCount === 1 ? 'y' : 'ies'}`
  return row.hiddenMatchCount > 0
    ? `+${replies} · ${formatNumber(row.hiddenMatchCount, 0)} matching`
    : `+${replies}`
}

/** What a screen reader hears for a row, since the map itself is a picture of marks. */
function describeRow(row: MapRow): string {
  const parts: string[] = []
  if (row.kind === 'compact') {
    parts.push(summaryLabel(row))
  } else {
    parts.push(row.comment.author ?? 'deleted')
    parts.push(`depth ${row.depth}`)
    parts.push(`${formatNumber(row.comment.text_plain.length, 0)} characters`)
    if (row.comment.entities.length > 0) {
      parts.push(`mentions ${row.comment.entities.map((e) => e.label).join(', ')}`)
    }
  }
  if (row.isOrphan) parts.push('reply to a comment that is not stored')
  if (row.isHit) parts.push('matches your search')
  if (row.isFocus) parts.push('selected')
  return parts.join(', ')
}

/**
 * The thread map: one block per comment, indented by depth, height by length.
 *
 * **Plain DOM, not SVG.** With no text inside the blocks every mark is an
 * axis-aligned rectangle, so the bands are a `linear-gradient`, the glow is a
 * `box-shadow`, and day/night theming is a CSS variable the browser resolves
 * itself — no `MutationObserver`, no redraw, unlike the scatter chart. It also
 * makes each row a real `<button>`, so tab order, Enter and screen-reader labels
 * are the platform's rather than a re-implementation.
 *
 * **Only the rows in view exist.** The largest stored thread draws a 22,000px
 * column; slicing to the viewport keeps ~20 rows and ~60 elements in the
 * document at any moment, which is what makes that affordable without a
 * virtualization dependency.
 */
export function DiscussionMap({
  layout,
  activeId,
  onFocus,
  onToggle,
  onGeometry,
}: DiscussionMapProps) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportHeight, setViewportHeight] = useState(600)

  useEffect(() => {
    const element = scrollRef.current
    if (element === null) return

    const measure = () => {
      setViewportHeight(element.clientHeight)
      onGeometry(element.clientWidth, element.clientHeight)
    }
    measure()

    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
    // `onGeometry` must be stable — it is a `useCallback` in the page — or this
    // would tear down and rebuild the observer on every render above it.
  }, [onGeometry])

  /**
   * Keep the active row in view — the map's half of the reader coordination.
   *
   * Driven by the active row rather than by the reader's scroll events, so the
   * two panes never chase each other: this runs when the reader reports a new
   * position (or a branch is chosen), never when this map is scrolled by hand.
   * Setting `scrollTop` triggers `onScroll` and re-windows the map, which is the
   * intent; it cannot loop, because nothing here depends on `scrollTop`.
   */
  useEffect(() => {
    const element = scrollRef.current
    if (element === null || activeId === null) return

    const row = layout.byId.get(activeId)
    if (row === undefined) return

    const viewTop = element.scrollTop
    const viewHeight = element.clientHeight
    if (viewHeight === 0) return

    // `.map-scroll` pads its content so the focus outline and search glow are
    // not clipped. `row.y` is measured from the spacer inside that padding, so
    // add it back before comparing against `scrollTop`.
    const paddingTop =
      Number.parseFloat(getComputedStyle(element).paddingTop) || 0
    const rowTop = row.y + paddingTop

    const margin = Math.min(viewHeight * FOLLOW_MARGIN_RATIO, FOLLOW_MARGIN_MAX)
    const inside =
      rowTop >= viewTop + margin &&
      rowTop + row.height <= viewTop + viewHeight - margin
    if (inside) return

    const centred = rowTop + row.height / 2 - viewHeight / 2
    const furthest = element.scrollHeight - viewHeight
    element.scrollTop = Math.max(0, Math.min(centred, furthest))
    // `viewportHeight` is in the deps because the first run can see a zero-height
    // pane; once `measure()` above reports the real height, this retries.
  }, [activeId, layout, viewportHeight])

  const hueBySlug = useMemo(() => {
    const hues = new Map<string, string>()
    for (const entry of layout.legend) {
      if (entry.hue !== null) hues.set(entry.slug, entry.hue)
    }
    return hues
  }, [layout.legend])

  const window = windowRows(layout, scrollTop, viewportHeight)
  const visible = layout.rows.slice(window.start, window.end)

  /** Arrow keys walk the rows that exist; the browser handles everything else. */
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return

    const buttons = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('[data-row-id]'),
    )
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
    if (index === -1) return

    const next = buttons[index + (event.key === 'ArrowDown' ? 1 : -1)]
    if (next === undefined) return

    event.preventDefault()
    // Focusing scrolls the row into view, which re-windows the map around it.
    next.focus()
  }

  return (
    <div className="map-pane">
      <div
        className="map-scroll"
        data-testid="discussion-map"
        onKeyDown={handleKeyDown}
        onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}
        ref={scrollRef}
        role="group"
        aria-label="Thread map"
      >
        <div className="map-spacer" style={{ height: layout.totalHeight }}>
          {visible.map((row) => (
            <MapRowView
              hueBySlug={hueBySlug}
              isReading={row.id === activeId}
              key={row.id}
              onFocus={onFocus}
              onToggle={onToggle}
              row={row}
            />
          ))}
        </div>
      </div>

      <MapLegend layout={layout} />
    </div>
  )
}

function MapRowView({
  row,
  hueBySlug,
  isReading,
  onFocus,
  onToggle,
}: {
  row: MapRow
  hueBySlug: Map<string, string>
  isReading: boolean
  onFocus: (id: number) => void
  onToggle: (id: number) => void
}) {
  const background =
    row.kind === 'block'
      ? bands(row.entities.map((entity) => hueBySlug.get(entity.slug) ?? ''))
      : undefined

  const className = [
    'map-row',
    `map-row--${row.kind}`,
    row.kind === 'block' && row.entities.length === 0 ? 'map-row--plain' : '',
    row.isDimmed ? 'is-dimmed' : '',
    row.isHit ? 'is-hit' : '',
    row.isFocus ? 'is-focus' : '',
    isReading ? 'is-reading' : '',
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      aria-label={describeRow(row)}
      aria-pressed={row.kind === 'block' ? row.isFocus : undefined}
      className={className}
      data-row-id={row.id}
      onClick={() => (row.kind === 'compact' ? onToggle(row.id) : onFocus(row.id))}
      style={{
        background,
        height: row.height,
        left: row.x,
        top: row.y,
        width: row.width,
      }}
      title={
        row.kind === 'compact'
          ? summaryLabel(row)
          : `${row.comment.author ?? 'deleted'} · ${formatNumber(
              row.comment.text_plain.length,
              0,
            )} characters`
      }
      type="button"
    >
      {row.kind === 'compact' ? (
        <span className="map-row__label">{summaryLabel(row)}</span>
      ) : null}

      {/*
        The providers this block is about, written on it.

        A chip rather than bare text: the fill underneath is one of fourteen hues
        across two themes, and a chip carrying the surface colour is legible on
        all of them. `aria-hidden` because the row's own label already names them,
        and hearing each provider twice is worse than not hearing it on the mark.
      */}
      {row.kind === 'block' && row.entityLabels.length > 0 ? (
        <span aria-hidden="true" className="map-row__name">
          {row.entityLabels.join(' · ')}
        </span>
      ) : null}
    </button>
  )
}

function MapLegend({ layout }: { layout: MapLayout }) {
  if (layout.legend.length === 0) return null

  const coloured = layout.legend.filter((entry) => entry.hue !== null)
  const uncoloured = layout.legend.length - coloured.length

  return (
    <div className="map-legend" aria-label="Entities mentioned in this thread">
      {coloured.map((entry) => (
        <span className="map-legend__item" key={entry.slug}>
          <span
            aria-hidden="true"
            className="map-legend__swatch"
            style={{ background: entry.hue ?? undefined }}
          />
          {entry.label}
          <span className="muted">{formatNumber(entry.comments, 0)}</span>
        </span>
      ))}
      {uncoloured > 0 ? (
        <span className="map-legend__item muted">
          +{uncoloured} more uncoloured
        </span>
      ) : null}
      <span className="map-legend__item muted">
        <span aria-hidden="true" className="map-legend__swatch map-legend__swatch--plain" />
        no entity
      </span>
      <span className="map-legend__item muted">
        <span aria-hidden="true" className="map-legend__swatch map-legend__swatch--hit" />
        search hit
      </span>
    </div>
  )
}
