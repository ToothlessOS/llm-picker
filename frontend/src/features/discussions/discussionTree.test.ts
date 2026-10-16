import { describe, expect, it } from 'vitest'

import {
  commentTree,
  discussionComment,
  entityRef,
  vendorRef,
  type CommentSpec,
} from '../../test/factories'
import {
  blockHeight,
  buildDiscussionTree,
  ancestorIds,
  defaultDepthMode,
  layoutMap,
  matchesFilters,
  nearestDrawnRow,
  matchesSearch,
  resolveFocus,
  subtreeIds,
  windowRows,
  type MapOptions,
} from './discussionTree'

function tree(specs: readonly CommentSpec[]) {
  return buildDiscussionTree(commentTree(specs))
}

function sizeOf(built: ReturnType<typeof tree>, id: number): number {
  return built.nodes.get(id)?.subtreeSize ?? -1
}

function options(overrides: Partial<MapOptions> = {}): MapOptions {
  return {
    depth: 'all',
    collapsed: new Set<number>(),
    expanded: new Set<number>(),
    focusId: null,
    search: '',
    entities: [],
    hideQuietBranches: false,
    ...overrides,
  }
}

const PANE = 600

// ---------------------------------------------------------------------------

describe('blockHeight', () => {
  it('maps the corpus percentiles to the pinned heights', () => {
    // Measured over the 21,103 stored comments: p10 51, p25 98, p50 191, p75 363,
    // p90 633, p95 866, p99 1,523, max 5,738. These are golden values — the whole
    // point of the scale is that it behaves a specific way across this range.
    expect(
      [51, 98, 191, 363, 633, 866, 1523, 5738].map(blockHeight),
    ).toEqual([31, 38, 49, 64, 82, 94, 96, 96])
  })

  it('never decreases as a post gets longer', () => {
    let previous = 0
    for (let chars = 0; chars <= 6000; chars += 7) {
      const height = blockHeight(chars)
      expect(height).toBeGreaterThanOrEqual(previous)
      previous = height
    }
  })

  it('floors nonsense input instead of throwing', () => {
    expect(blockHeight(0)).toBe(14)
    expect(blockHeight(-100)).toBe(14)
  })

  it('caps a 5,738-character post at 96px, not 570', () => {
    // The named regression: without the clamp, one pasted log file would own a
    // third of the pane under a linear scale.
    expect(blockHeight(5738)).toBe(96)
    expect(blockHeight(50_000)).toBe(96)
  })
})

describe('buildDiscussionTree', () => {
  it('keeps pre-order and counts subtrees', () => {
    const built = tree([
      { id: 1, children: [{ id: 2, children: [{ id: 3 }] }] },
      { id: 4 },
    ])

    expect(built.order).toEqual([1, 2, 3, 4])
    expect(sizeOf(built, 1)).toBe(3)
    expect(sizeOf(built, 2)).toBe(2)
    expect(sizeOf(built, 3)).toBe(1)
    expect(built.roots).toEqual([1, 4])
  })

  it('counts a star correctly', () => {
    const built = tree([{ id: 1, children: [{ id: 2 }, { id: 3 }, { id: 4 }] }])

    expect(sizeOf(built, 1)).toBe(4)
    expect(sizeOf(built, 2)).toBe(1)
  })

  it('draws an orphan as a root rather than dropping it', () => {
    // What a trimmed response looks like: a depth-2 comment whose ancestors are
    // not in the payload. Nobody should ever send one — the map refuses to pass
    // the trim parameters for exactly this reason — but the failure has to be
    // visible rather than silent.
    const built = buildDiscussionTree([
      discussionComment({ hn_id: 5, parent_hn_id: 999, depth: 2, path: '000000.000000.000001' }),
    ])

    expect(built.roots).toEqual([5])
    expect(built.orphans).toEqual([5])
    expect(built.nodes.get(5)?.isOrphan).toBe(true)
    // Drawn at the left margin, because that is where it now sits.
    expect(built.nodes.get(5)?.renderDepth).toBe(0)
    expect(layoutMap(built, options(), PANE).rows).toHaveLength(1)
  })

  it('keeps the replies of a deleted parent', () => {
    const built = buildDiscussionTree([
      discussionComment({ hn_id: 1, is_deleted: true, author: null, text_html: '', text_plain: '' }),
      discussionComment({ hn_id: 2, parent_hn_id: 1, depth: 1, path: '000000.000000' }),
    ])

    expect(sizeOf(built, 1)).toBe(2)
    expect(subtreeIds(built, 1)).toEqual([1, 2])
  })

  it('treats a child that arrives before its parent as an orphan, so no cycle forms', () => {
    const built = buildDiscussionTree([
      discussionComment({ hn_id: 2, parent_hn_id: 1, depth: 1, path: '000000.000000' }),
      discussionComment({ hn_id: 1, depth: 0, path: '000001' }),
    ])

    expect(built.roots).toEqual([2, 1])
    expect(built.orphans).toEqual([2])
    expect(ancestorIds(built, 2)).toEqual([])
  })

  it('handles an empty thread without throwing', () => {
    const built = buildDiscussionTree([])

    expect(built.order).toEqual([])
    expect(built.roots).toEqual([])
    expect(layoutMap(built, options(), PANE).totalHeight).toBe(0)
  })

  it('ignores a duplicate id rather than rendering it twice', () => {
    const built = buildDiscussionTree([
      discussionComment({ hn_id: 1 }),
      discussionComment({ hn_id: 1, path: '000001' }),
    ])

    expect(built.order).toEqual([1])
  })
})

describe('subtreeIds and ancestorIds', () => {
  const built = tree([{ id: 1, children: [{ id: 2, children: [{ id: 3 }] }, { id: 4 }] }])

  it('returns a pre-order slice, inclusive of the node', () => {
    expect(subtreeIds(built, 2)).toEqual([2, 3])
    expect(subtreeIds(built, 4)).toEqual([4])
    expect(subtreeIds(built, 999)).toEqual([])
  })

  it('returns ancestors root first and excludes the node', () => {
    expect(ancestorIds(built, 3)).toEqual([1, 2])
    expect(ancestorIds(built, 1)).toEqual([])
  })
})

describe('resolveFocus', () => {
  const built = tree([{ id: 42, children: [{ id: 43 }] }])

  it('accepts an id as a number or a string', () => {
    expect(resolveFocus(built, 42)).toBe(42)
    expect(resolveFocus(built, '42')).toBe(42)
  })

  it('accepts an exact path', () => {
    expect(resolveFocus(built, '000000.000000')).toBe(43)
  })

  it('returns null for a stale link rather than throwing', () => {
    // The recovery path for a URL shared before a refetch: the reader falls back
    // to the whole thread and says so.
    expect(resolveFocus(built, '999999')).toBeNull()
    expect(resolveFocus(built, '000000.000007')).toBeNull()
    expect(resolveFocus(built, '')).toBeNull()
    expect(resolveFocus(built, null)).toBeNull()
    expect(resolveFocus(built, undefined)).toBeNull()
  })

  it('tries the path before the id', () => {
    // The only way a padded path can also read as an id is `hn_id: 0`, since
    // `parseInt` of a zero-padded first group is always 0. Hacker News has never
    // issued id 0, so this is a synthetic fixture — but the precedence is a real
    // rule and this is the only shape that can observe it.
    const colliding = tree([{ id: 123456 }, { id: 0 }])

    expect(resolveFocus(colliding, '000000')).toBe(123456)
    expect(resolveFocus(colliding, '000001')).toBe(0)
  })

  it('still accepts a plain id that is not a path', () => {
    expect(resolveFocus(tree([{ id: 2 }]), '000009')).toBeNull()
  })
})

describe('matchesSearch', () => {
  it('is case-insensitive and ignores surrounding space', () => {
    const comment = discussionComment({ text_plain: 'I use Claude daily' })

    expect(matchesSearch(comment, 'claude')).toBe(true)
    expect(matchesSearch(comment, 'CLAUDE')).toBe(true)
    expect(matchesSearch(comment, '  claude  ')).toBe(true)
    expect(matchesSearch(comment, 'gemini')).toBe(false)
  })

  it('treats an empty term as no search at all', () => {
    const comment = discussionComment()

    expect(matchesSearch(comment, '')).toBe(false)
    expect(matchesSearch(comment, '   ')).toBe(false)
  })

  it('reads the plain text, so a term in an attribute does not match', () => {
    // `q=href` matching every post containing a link is the failure this avoids,
    // and it is why the map never searches `text_html`.
    const comment = discussionComment({
      text_html: '<p>See <a href="https://example.com/claude">the docs</a></p>',
      text_plain: 'See the docs',
    })

    expect(matchesSearch(comment, 'href')).toBe(false)
    expect(matchesSearch(comment, 'example.com')).toBe(false)
    expect(matchesSearch(comment, 'claude')).toBe(false)
    expect(matchesSearch(comment, 'docs')).toBe(true)
  })

  it('treats regex metacharacters literally', () => {
    const comment = discussionComment({ text_plain: 'costs $5 (roughly)' })

    expect(matchesSearch(comment, '$5')).toBe(true)
    expect(matchesSearch(comment, '(rough')).toBe(true)
    expect(matchesSearch(comment, '.*')).toBe(false)
  })
})

describe('matchesFilters — the vendor roll-up', () => {
  const claudeOnly = discussionComment({ entities: [entityRef()] })
  const anthropicOnly = discussionComment({ entities: [vendorRef('anthropic', 'Anthropic')] })
  const codex = discussionComment({
    entities: [entityRef({ slug: 'claude-code', label: 'Claude Code', vendor: 'anthropic' })],
  })

  it('lights up a service when its vendor is filtered', () => {
    expect(matchesFilters(claudeOnly, ['anthropic'])).toBe(true)
  })

  it('lights up the service when it is filtered directly', () => {
    expect(matchesFilters(claudeOnly, ['claude'])).toBe(true)
  })

  it('does not roll a vendor down to an arbitrary service', () => {
    // Deliberate asymmetry, mirroring the endpoint: filtering by `claude` asks
    // about the service, not about Anthropic the company.
    expect(matchesFilters(anthropicOnly, ['claude'])).toBe(false)
  })

  it('does not let a sibling service stand in for another', () => {
    // `claude-code`'s vendor is `anthropic`, not `claude` — the surprising case,
    // pinned because it is the one a reader would assume works.
    expect(matchesFilters(codex, ['claude'])).toBe(false)
    expect(matchesFilters(codex, ['anthropic'])).toBe(true)
  })

  it('matches nothing when no filter is active', () => {
    expect(matchesFilters(claudeOnly, [])).toBe(false)
  })
})

describe('defaultDepthMode', () => {
  it('opens everything for a thread small enough to read', () => {
    expect(defaultDepthMode(0)).toBe('all')
    expect(defaultDepthMode(150)).toBe('all')
  })

  it('falls back to the first layer past that', () => {
    // 71 of the 113 stored threads are on the first side of this line; the
    // largest is 1,532 comments and 133 top-level branches on the other.
    expect(defaultDepthMode(151)).toBe('layer1')
    expect(defaultDepthMode(1532)).toBe('layer1')
  })
})

describe('layoutMap', () => {
  it('accumulates y in pre-order with a gap between rows', () => {
    const built = tree([
      { id: 1, text: 'x'.repeat(51) }, // 31px
      { id: 2, text: 'x'.repeat(98) }, // 38px
      { id: 3, text: 'x'.repeat(191) }, // 49px
    ])

    const layout = layoutMap(built, options(), PANE)

    expect(layout.rows.map((row) => row.y)).toEqual([0, 33, 73])
    expect(layout.totalHeight).toBe(73 + 49)
  })

  it('indents by depth and keeps every block inside the pane', () => {
    const built = tree([{ id: 1, children: [{ id: 2, children: [{ id: 3 }] }] }])

    const layout = layoutMap(built, options(), PANE)

    expect(layout.rows.map((row) => row.x)).toEqual([6, 20, 34])
    for (const row of layout.rows) {
      expect(row.x + row.width).toBeLessThanOrEqual(PANE)
    }
  })

  it('slides the rows below a collapse upwards', () => {
    const built = tree([
      { id: 1, text: 'x'.repeat(51) }, // 31px
      { id: 2, text: 'x'.repeat(98), children: [{ id: 4, text: 'x'.repeat(191) }] }, // 38px over 49px
      { id: 3, text: 'x'.repeat(191) }, // 49px
    ])
    const open = layoutMap(built, options(), PANE)
    const shut = layoutMap(built, options({ collapsed: new Set([2]) }), PANE)

    const openY = new Map(open.rows.map((row) => [row.id, row.y]))
    const shutY = new Map(shut.rows.map((row) => [row.id, row.y]))

    // Row 3 moves up by exactly what row 2 stopped occupying: its own block (38)
    // and the reply it stood in for (49 + a gap), less the compact bar (16) that
    // takes their place. A collapsed branch is cheaper than an open one, not free.
    const reclaimed = 38 - 16 + 49 + 2
    expect((openY.get(3) as number) - (shutY.get(3) as number)).toBe(reclaimed)
    expect(open.totalHeight - shut.totalHeight).toBe(reclaimed)
    expect(shut.rows.map((row) => row.id)).toEqual([1, 2, 3])
  })

  it('emits one row for a collapsed branch, not one per descendant', () => {
    // The cost the collapse exists to avoid: without the subtree skip, a
    // collapsed 500-comment branch would still emit 500 rows.
    const built = tree([
      { id: 1, children: [{ id: 2, children: [{ id: 3 }, { id: 4 }] }, { id: 5 }] },
    ])

    const layout = layoutMap(built, options({ collapsed: new Set([2]) }), PANE)

    expect(layout.rows.map((row) => row.id)).toEqual([1, 2, 5])
    expect(layout.rows[1].hiddenCount).toBe(2)
  })

  it('drops whole branches when asked, rather than collapsing them', () => {
    const built = tree([{ id: 1 }, { id: 2 }])

    const layout = layoutMap(
      built,
      options({ search: 'nomatch', hideQuietBranches: true }),
      PANE,
    )

    expect(layout.rows).toEqual([])
    expect(layout.hiddenTotal).toBe(2)
  })

  it('keeps rows ascending by y, which windowRows depends on', () => {
    const built = tree([
      { id: 1, children: [{ id: 2, children: [{ id: 3 }] }] },
      { id: 4, children: [{ id: 5 }] },
    ])

    const layout = layoutMap(built, options({ collapsed: new Set([3]) }), PANE)

    for (let index = 1; index < layout.rows.length; index += 1) {
      expect(layout.rows[index].y).toBeGreaterThan(layout.rows[index - 1].y)
    }
  })

  describe('the depth modes', () => {
    const built = tree([
      { id: 1, children: [{ id: 2, children: [{ id: 3, children: [{ id: 4 }] }] }] },
    ])

    it('draws only the top level', () => {
      const layout = layoutMap(built, options({ depth: 'roots' }), PANE)

      expect(layout.rows.map((row) => [row.id, row.kind])).toEqual([
        [1, 'block'],
        [2, 'compact'],
      ])
      expect(layout.rows[1].hiddenCount).toBe(2)
    })

    it('draws the first layer of replies', () => {
      const layout = layoutMap(built, options({ depth: 'layer1' }), PANE)

      expect(layout.rows.map((row) => [row.id, row.kind])).toEqual([
        [1, 'block'],
        [2, 'block'],
        [3, 'compact'],
      ])
    })

    it('draws everything', () => {
      const layout = layoutMap(built, options({ depth: 'all' }), PANE)

      expect(layout.rows.every((row) => row.kind === 'block')).toBe(true)
      expect(layout.hiddenTotal).toBe(0)
    })

    it('hides a leaf rather than drawing a bar that stands in for nothing', () => {
      // A depth limit reached exactly at a leaf has nothing to summarise. Emitting
      // a compact row anyway would fill a deep thread with thousands of "+0
      // replies" marks.
      const leafy = tree([{ id: 1, children: [{ id: 2 }] }])

      const layout = layoutMap(leafy, options({ depth: 'roots' }), PANE)

      expect(layout.rows.map((row) => row.id)).toEqual([1])
      expect(layout.hiddenTotal).toBe(1)
    })
  })

  describe('the filter regime', () => {
    const built = tree([
      {
        id: 1,
        children: [
          { id: 2, children: [{ id: 3, text: 'I like gemini' }] },
          { id: 4, children: [{ id: 5, text: 'nothing here' }] },
        ],
      },
    ])

    it('collapses a branch with no match and keeps the path to one that has it', () => {
      const layout = layoutMap(built, options({ search: 'gemini' }), PANE)

      // Everything on the path to the hit is drawn; the sibling branch is one bar.
      expect(layout.rows.map((row) => [row.id, row.kind])).toEqual([
        [1, 'block'],
        [2, 'block'],
        [3, 'block'],
        [4, 'compact'],
      ])
    })

    it('remembers how many hidden comments matched', () => {
      const layout = layoutMap(built, options({ search: 'nothing' }), PANE)

      expect(layout.rows.map((row) => row.id)).toEqual([1, 2, 4, 5])
      expect(layout.rows.find((row) => row.id === 2)?.hiddenMatchCount).toBe(0)
    })

    it('counts matches across the whole thread, not just the drawn rows', () => {
      const layout = layoutMap(built, options({ search: 'gemini' }), PANE)

      expect(layout.matchTotal).toBe(1)
    })

    it('marks the rows that hold the search term', () => {
      const layout = layoutMap(built, options({ search: 'gemini' }), PANE)

      expect(layout.rows.filter((row) => row.isHit).map((row) => row.id)).toEqual([3])
    })
  })

  describe('collapse precedence', () => {
    const built = tree([
      { id: 1, children: [{ id: 2, children: [{ id: 3 }] }] },
    ])

    it('lets an explicit expansion beat an explicit collapse', () => {
      const layout = layoutMap(
        built,
        options({ collapsed: new Set([2]), expanded: new Set([2]) }),
        PANE,
      )

      expect(layout.rows.map((row) => [row.id, row.kind])).toEqual([
        [1, 'block'],
        [2, 'block'],
        [3, 'block'],
      ])
    })

    it('always opens the focus and its ancestors, so a deep link cannot land on a hidden node', () => {
      const layout = layoutMap(
        built,
        options({ depth: 'roots', focusId: 3 }),
        PANE,
      )

      // 'roots' would collapse everything past depth 0 — but the spine to 3 wins.
      expect(layout.rows.map((row) => [row.id, row.kind])).toEqual([
        [1, 'block'],
        [2, 'block'],
        [3, 'block'],
      ])
    })
  })

  describe('dimming', () => {
    const built = tree([
      {
        id: 1,
        children: [
          { id: 2, children: [{ id: 3 }] },
          { id: 4 },
        ],
      },
    ])

    it('dims everything outside the focus subtree and its ancestors', () => {
      const layout = layoutMap(built, options({ focusId: 2 }), PANE)

      const dimmed = layout.rows.filter((row) => row.isDimmed).map((row) => row.id)
      // 4 is a sibling branch; 1 is an ancestor and 2 and 3 are the subtree.
      expect(dimmed).toEqual([4])
    })

    it('keeps a match bright and dims the context on the way to it', () => {
      const filtered = tree([
        { id: 1, children: [{ id: 2, entities: [vendorRef('openai', 'OpenAI')] }] },
      ])

      const layout = layoutMap(filtered, options({ entities: ['openai'] }), PANE)

      // The parent is drawn because something under it matched, and greyed because
      // it is not itself what the filter asked for.
      expect(layout.rows.map((row) => [row.id, row.isDimmed])).toEqual([
        [1, true],
        [2, false],
      ])
    })

    it('hides a non-matching leaf entirely rather than dimming it', () => {
      const filtered = tree([
        { id: 1, entities: [vendorRef('openai', 'OpenAI')] },
        { id: 2, entities: [entityRef()] },
      ])

      const layout = layoutMap(filtered, options({ entities: ['openai'] }), PANE)

      // Filtering is not "grey out the rest" — a comment with nothing to do with
      // the question is not worth a row, and there would be thousands of them.
      expect(layout.rows.map((row) => row.id)).toEqual([1])
    })

    it('dims nothing when no focus and no filter is set', () => {
      const layout = layoutMap(built, options(), PANE)

      expect(layout.rows.some((row) => row.isDimmed)).toBe(false)
    })
  })

  describe('the legend and the bands', () => {
    it('assigns one hue per entity, most mentioned first', () => {
      const built = tree([
        { id: 1, entities: [vendorRef('openai', 'OpenAI')] },
        { id: 2, entities: [vendorRef('openai', 'OpenAI')] },
        { id: 3, entities: [entityRef()] },
      ])

      const layout = layoutMap(built, options(), PANE)

      expect(layout.legend.map((entry) => [entry.slug, entry.comments])).toEqual([
        ['openai', 2],
        ['claude', 1],
      ])
      expect(layout.legend[0].hue).toBe('var(--map-hue-1)')
      expect(layout.legend[1].hue).toBe('var(--map-hue-2)')
    })

    it('bands a block that mentions several entities, in legend order', () => {
      // Cannot happen in today's data — every tagged comment has exactly one tag
      // — but the encoding has to be correct for the day it can, and this is the
      // fixture the segmented-fill branch is validated against.
      const built = tree([
        { id: 1, entities: [vendorRef('openai', 'OpenAI'), entityRef()] },
        { id: 2, entities: [vendorRef('openai', 'OpenAI')] },
        { id: 3, entities: [vendorRef('openai', 'OpenAI')] },
      ])

      const layout = layoutMap(built, options(), PANE)

      // `openai` is mentioned more, so it takes hue 1 and sorts first.
      expect(layout.rows[0].entities.map((entity) => entity.slug)).toEqual([
        'openai',
        'claude',
      ])
      expect(layout.rows[0].uncolouredEntities).toBe(0)
    })

    it('leaves entities past the end of the palette uncoloured rather than reusing a hue', () => {
      const entities = Array.from({ length: 16 }, (_, index) =>
        vendorRef(`vendor-${String(index).padStart(2, '0')}`),
      )
      const built = tree([{ id: 1, entities }])

      const layout = layoutMap(built, options(), PANE)

      expect(layout.legend.filter((entry) => entry.hue !== null)).toHaveLength(14)
      expect(layout.legend.filter((entry) => entry.hue === null)).toHaveLength(2)
      expect(layout.rows[0].entities).toHaveLength(14)
      expect(layout.rows[0].uncolouredEntities).toBe(2)
    })
  })
})

describe('nearestDrawnRow', () => {
  // A chain, drawn to the top level only: row 1 is a block, row 2 a collapsed
  // bar standing in for 3 and 4, which are not drawn at all.
  const built = tree([
    { id: 1, children: [{ id: 2, children: [{ id: 3, children: [{ id: 4 }] }] }] },
  ])
  const layout = layoutMap(built, options({ depth: 'roots' }), PANE)

  it('points at a comment that has a row of its own', () => {
    expect(nearestDrawnRow(built, layout, 1)).toBe(1)
  })

  it('falls back to the closest drawn ancestor', () => {
    // Without this the map simply stops moving partway down a large thread,
    // because most comments being read are below the drawn depth.
    expect(nearestDrawnRow(built, layout, 3)).toBe(2)
    expect(nearestDrawnRow(built, layout, 4)).toBe(2)
  })

  it('is unaffected by how deep the comment is', () => {
    const deep = tree([
      {
        id: 1,
        children: [
          { id: 2, children: [{ id: 3, children: [{ id: 4, children: [{ id: 5 }] }] }] },
        ],
      },
    ])
    const shallowLayout = layoutMap(deep, options({ depth: 'layer1' }), PANE)

    expect(nearestDrawnRow(deep, shallowLayout, 5)).toBe(3)
  })

  it('returns nothing for a comment that is not in the tree', () => {
    // A stale `?comment=` from a URL shared before a refetch.
    expect(nearestDrawnRow(built, layout, 999)).toBeNull()
    expect(nearestDrawnRow(built, layout, null)).toBeNull()
  })
})

describe('windowRows', () => {
  const built = tree(
    Array.from({ length: 40 }, (_, index) => ({ id: index + 1, text: 'x'.repeat(191) })),
  )
  const layout = layoutMap(built, options(), PANE) // 40 rows of 49+2 px

  it('returns only what the viewport and its overscan cover', () => {
    const window = windowRows(layout, 0, 200)

    expect(window.start).toBe(0)
    expect(window.end).toBeLessThan(layout.rows.length)
    // 200px of viewport plus 400px of overscan covers about twelve 51px rows.
    expect(window.end - window.start).toBeLessThan(16)
  })

  it('finds the middle of a long column by binary search', () => {
    const middle = layout.rows[20]
    const window = windowRows(layout, middle.y, 200)

    expect(window.start).toBeLessThanOrEqual(20)
    expect(window.end).toBeGreaterThan(20)
  })

  it('reaches the last row at the bottom of the scroll', () => {
    const window = windowRows(layout, layout.totalHeight - 200, 200)

    expect(window.end).toBe(layout.rows.length)
  })

  it('returns everything when the column is shorter than the viewport', () => {
    const short = layoutMap(tree([{ id: 1 }]), options(), PANE)
    const window = windowRows(short, 0, 800)

    expect(window).toEqual({ start: 0, end: 1 })
  })

  it('clamps instead of returning nothing when scrolled past the end', () => {
    const window = windowRows(layout, 10 ** 6, 200)

    expect(window.end).toBe(layout.rows.length)
    expect(window.start).toBeLessThanOrEqual(layout.rows.length)
  })

  it('returns an empty window for an empty thread', () => {
    const empty = layoutMap(buildDiscussionTree([]), options(), PANE)

    expect(windowRows(empty, 0, 200)).toEqual({ start: 0, end: 0 })
  })
})
