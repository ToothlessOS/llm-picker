import type { DiscussionEntityRef, EntityKind } from '../api'

/**
 * The map's colour channel.
 *
 * Hues ship as **CSS custom properties rather than hex literals**. That is what
 * lets a theme flip repaint with no JavaScript at all: the browser resolves
 * `var(--map-hue-3)` against whatever `:root` or `[data-theme="night"]` says. The
 * existing scatter chart cannot do this — it bakes hex values into SVG attributes
 * and therefore needs a `MutationObserver` on `document.documentElement` plus a
 * full redraw — and not repeating that is most of why the map is plain DOM.
 *
 * Fourteen because that is how many hues stay distinguishable as *fills* at a
 * 14px block height on both themes. Measured against the live bank, a thread
 * mentions a median of 5 distinct entities and a p90 of 16, so the palette covers
 * 90% of threads completely; beyond it, entities keep their label in the legend
 * and in the reader's chips but go uncoloured rather than sharing a hue.
 */
export const MAP_HUE_COUNT = 14

/** `--map-hue-1` … `--map-hue-14`, wrapping for callers that do not pre-check. */
export function mapHueVar(index: number): string {
  return `var(--map-hue-${(index % MAP_HUE_COUNT) + 1})`
}

/** One entity's presence in a thread, before hues are assigned. */
export interface EntityTally {
  slug: string
  label: string
  kind: EntityKind
  /** The vendor a service rolls up to, so a client can show the roll-up. */
  vendor: string | null
  /** How many comments mention it. Drives both the ordering and the legend. */
  comments: number
}

export interface LegendEntry extends EntityTally {
  /** The CSS variable to fill with, or `null` past the end of the palette. */
  hue: string | null
}

/**
 * The legend, and the hue assignment for a whole thread.
 *
 * **Assignment is per thread, not global**, and that is deliberate. A global
 * mapping of the 52-entity vocabulary onto 14 hues collides: with a p90 of 16
 * entities per thread, two entities in the *same view* would share a colour and
 * the encoding would lie. Assigning by position in this thread guarantees the
 * colours on screen are distinct.
 *
 * The cost is that an entity's hue differs between threads. That is acceptable
 * because colour is never the only carrier — the legend names every hue, and the
 * reader spells the entities out in text — and it is the price of the guarantee
 * that matters, which is that *within one map* a colour means exactly one thing.
 */
export function buildLegend(
  entities: Iterable<DiscussionEntityRef>,
  commentCounts: ReadonlyMap<string, number>,
): LegendEntry[] {
  const seen = new Map<string, EntityTally>()

  for (const entity of entities) {
    if (seen.has(entity.slug)) continue
    seen.set(entity.slug, {
      slug: entity.slug,
      label: entity.label,
      kind: entity.kind,
      vendor: entity.vendor,
      comments: commentCounts.get(entity.slug) ?? 0,
    })
  }

  return [...seen.values()]
    .sort(
      (left, right) =>
        right.comments - left.comments || left.slug.localeCompare(right.slug),
    )
    .map((entry, index) => ({
      ...entry,
      hue: index < MAP_HUE_COUNT ? mapHueVar(index) : null,
    }))
}
