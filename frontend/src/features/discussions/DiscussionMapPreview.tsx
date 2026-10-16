import { useQuery } from '@tanstack/react-query'

import { getMetadata } from '../../api'
import { formatNumber } from '../../app/format'

/**
 * A miniature of the map, for the home page card.
 *
 * **Hand-authored rather than live**, and deliberately: the other previews share
 * one already-needed `/overview/` query, whereas drawing a real map would fetch a
 * thread's comment tree — up to a megabyte — to paint a 200px thumbnail. The
 * counts in the caption are real, and come from the `meta` block `AppShell`
 * already has in the cache, so the card still reports live numbers for free.
 *
 * The marks follow the real encoding so the card teaches it: indent is depth,
 * height is post length, colour is the entity mentioned, and one block is ringed
 * because it matches the search.
 */
const PREVIEW_ROWS: ReadonlyArray<{
  depth: number
  width: number
  height: number
  hue?: string
  hit?: boolean
  more?: string
}> = [
  { depth: 0, width: 88, height: 13, hue: 'var(--map-hue-1)' },
  { depth: 1, width: 64, height: 9 },
  { depth: 2, width: 74, height: 11, hue: 'var(--map-hue-2)' },
  { depth: 3, width: 40, height: 6, more: '+34' },
  { depth: 1, width: 52, height: 8, hue: 'var(--map-hue-1)' },
  { depth: 0, width: 70, height: 10, hit: true },
  { depth: 1, width: 46, height: 7, hue: 'var(--map-hue-3)' },
  { depth: 2, width: 30, height: 5, more: '+8' },
  { depth: 0, width: 58, height: 9, hue: 'var(--map-hue-4)' },
  { depth: 1, width: 34, height: 6 },
]

export function DiscussionMapPreview() {
  const metadata = useQuery({
    queryKey: ['metadata'],
    queryFn: ({ signal }) => getMetadata({ signal }),
    // The shell already polls this on the same key, so this shares its cache
    // rather than adding a request.
    refetchInterval: 60_000,
  })

  const counts = metadata.data?.discussions?.counts

  return (
    <>
      <div className="viz-stage__canvas viz-stage__canvas--live">
        <div className="map-preview" aria-hidden="true">
          {PREVIEW_ROWS.map((row, index) => (
            <span className="map-preview__line" key={index}>
              <span
                className={`map-preview__row${row.hit ? ' is-hit' : ''}${
                  row.hue === undefined ? ' map-preview__row--plain' : ''
                }`}
                style={{
                  background: row.hue,
                  height: row.height,
                  marginLeft: row.depth * 9,
                  width: `${row.width}%`,
                }}
              />
              {row.more ? (
                <span className="map-preview__more">{row.more}</span>
              ) : null}
            </span>
          ))}
        </div>
      </div>
      <p className="viz-stage__caption">
        {counts
          ? `${formatNumber(counts.threads, 0)} threads · ${formatNumber(
              counts.comments,
              0,
            )} comments · ${formatNumber(counts.entities, 0)} providers and services`
          : 'LLM discussions from Hacker News'}
      </p>
    </>
  )
}
