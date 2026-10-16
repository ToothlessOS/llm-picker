/**
 * The discussion map: its geometry, its collapse rules, and its layout.
 *
 * Pure by construction — no React, no DOM, no d3 — so every decision the
 * visualization makes is decidable in a unit test, and the components below it
 * only paint what this module returns. The one import is a `import type`, which
 * the compiler erases.
 *
 * Two things make this simpler than a general tree layout, and both come from the
 * backend rather than from cleverness here:
 *
 * 1. `comments` arrives **flat, ordered by `path`**, and `path` is the zero-padded
 *    chain of sibling indices — so the array is already a pre-order traversal. A
 *    node's descendants are the *contiguous* slice that follows it, which makes
 *    `subtreeIds` a `slice` and the `y` accumulation a single forward pass. There
 *    is no graph algorithm to run and nothing for `d3.hierarchy` to do.
 * 2. `depth` and `parent_hn_id` are both present, so a node whose parent is
 *    missing can still be placed (see `isOrphan`).
 */

import type { DiscussionComment, DiscussionEntityRef } from '../../api'
import { buildLegend, type LegendEntry } from '../../app/palette'

// ---------------------------------------------------------------------------
// Height
// ---------------------------------------------------------------------------

/**
 * The most a comment's height can be earned by: roughly the corpus p95 (866
 * characters, measured over 21,103 stored comments).
 */
const LENGTH_CAP = 900
/** Concavity. Below 1 compresses the tail while keeping the body ordered. */
const HEIGHT_GAMMA = 0.55

export const MIN_BLOCK_HEIGHT = 14
export const MAX_BLOCK_HEIGHT = 96
/** A collapsed subtree is a single thin bar, so hiding is much cheaper than showing. */
export const COMPACT_ROW_HEIGHT = 16
export const ROW_GAP = 2
export const INDENT = 14
/** Left gutter, so a root's reply spine has somewhere to sit. */
export const GUTTER = 6
/** A block never narrows past this, whatever the depth. */
const MIN_BLOCK_WIDTH = 60
/** Room for the block's right edge, so it never touches the scrollbar. */
const RIGHT_PAD = 8

/**
 * Length → height, as a saturating power law.
 *
 * Comment length in the live bank is heavy-tailed: p50 191, p90 633, p99 1,523,
 * max 5,738 — a 30× span, with the tail made of pasted logs rather than argument.
 * Each of the obvious alternatives fails a specific way:
 *
 * * **Linear** — the max post is 30× the median, so one paste owns the pane while
 *   the p25→p75 band (98→363 chars) differs by a few pixels. It over-serves
 *   exactly the posts nobody reads.
 * * **Logarithmic** — fixes the tail but flattens the body: `log(363)/log(191) =
 *   1.11`, so a p75 post is 11% taller than a median one and the distinctions a
 *   reader actually uses to skip disappear.
 * * **Clamped power law** — strictly increasing, so the body stays ordered, and
 *   concave, so the tail compresses. The clamp is what bounds the worst case:
 *   **no block is ever more than 96/14 ≈ 6.9× another**, however long the post.
 *
 * Measured against the corpus this gives a mean height of ~53px at a ~55px row
 * pitch, so a screen holds ~11 comments.
 */
export function blockHeight(chars: number): number {
  const clamped = Math.min(Math.max(chars, 0), LENGTH_CAP)
  const t = clamped / LENGTH_CAP
  return Math.round(
    MIN_BLOCK_HEIGHT +
      Math.pow(t, HEIGHT_GAMMA) * (MAX_BLOCK_HEIGHT - MIN_BLOCK_HEIGHT),
  )
}

// ---------------------------------------------------------------------------
// Tree
// ---------------------------------------------------------------------------

export interface DiscussionTreeNode {
  comment: DiscussionComment
  /** The depth the server reported. Kept for display; may exceed `renderDepth`. */
  depth: number
  /**
   * Distance from the root **as drawn**. Identical to `depth` for a well-formed
   * response; smaller for an orphan, whose parent is not in the payload. The
   * layout indents by this, so an orphan sits at the left margin and says so in
   * its label rather than floating at an indent with nothing above it.
   */
  renderDepth: number
  parentId: number | null
  childIds: number[]
  /** Stored descendants **including self**. */
  subtreeSize: number
  /** Position in `order`, so `subtreeIds` is a slice rather than a search. */
  position: number
  /**
   * True when `parent_hn_id` names a comment this payload does not contain — a
   * deleted parent, or a response that was trimmed server-side.
   */
  isOrphan: boolean
}

export interface DiscussionTree {
  nodes: Map<number, DiscussionTreeNode>
  /** Pre-order, i.e. the input's order. */
  order: number[]
  roots: number[]
  orphans: number[]
  byPath: Map<string, number>
  maxDepth: number
}

/**
 * Build the tree from the flat comment array.
 *
 * Two passes, no recursion: a 16-deep thread is fine either way, but a corrupted
 * 10,000-deep one must not blow the stack, and the ingest cap is a setting.
 *
 * The array is pre-order, so a parent is always seen before its children. That is
 * load-bearing: a child that arrived *before* its parent is therefore treated as
 * an orphan — it cannot form a cycle, and a duplicate id cannot become two rows.
 */
export function buildDiscussionTree(
  comments: readonly DiscussionComment[],
): DiscussionTree {
  const nodes = new Map<number, DiscussionTreeNode>()
  const order: number[] = []
  const roots: number[] = []
  const orphans: number[] = []
  const byPath = new Map<string, number>()

  for (const comment of comments) {
    if (nodes.has(comment.hn_id)) continue

    const parent =
      comment.parent_hn_id === null
        ? undefined
        : nodes.get(comment.parent_hn_id)

    const node: DiscussionTreeNode = {
      comment,
      depth: comment.depth,
      renderDepth: parent ? parent.renderDepth + 1 : 0,
      parentId: parent ? parent.comment.hn_id : null,
      childIds: [],
      subtreeSize: 1,
      position: order.length,
      isOrphan: false,
    }

    nodes.set(comment.hn_id, node)
    order.push(comment.hn_id)
    byPath.set(comment.path, comment.hn_id)

    if (parent) {
      parent.childIds.push(comment.hn_id)
    } else {
      // A `null` parent is an ordinary top-level comment. Anything else names a
      // parent this response does not have, and drawing it as a root is what
      // keeps a trimmed payload from silently losing part of the thread.
      if (comment.parent_hn_id !== null) {
        node.isOrphan = true
        orphans.push(comment.hn_id)
      }
      roots.push(comment.hn_id)
    }
  }

  // Reverse pre-order is a valid bottom-up order — every child appears after its
  // parent in `order`, so by the time a node is reached all of its descendants
  // have already been folded into it.
  for (let index = order.length - 1; index >= 0; index -= 1) {
    const node = nodes.get(order[index]) as DiscussionTreeNode
    if (node.parentId !== null) {
      const parent = nodes.get(node.parentId)
      if (parent) parent.subtreeSize += node.subtreeSize
    }
  }

  let maxDepth = 0
  for (const node of nodes.values()) {
    if (node.depth > maxDepth) maxDepth = node.depth
  }

  return { nodes, order, roots, orphans, byPath, maxDepth }
}

/** The node and every descendant, in pre-order. */
export function subtreeIds(tree: DiscussionTree, id: number): number[] {
  const node = tree.nodes.get(id)
  if (!node) return []
  return tree.order.slice(node.position, node.position + node.subtreeSize)
}

/** Every ancestor, root first, **excluding** the node itself. */
export function ancestorIds(tree: DiscussionTree, id: number): number[] {
  const ancestors: number[] = []
  let current = tree.nodes.get(id)?.parentId ?? null

  while (current !== null) {
    ancestors.push(current)
    current = tree.nodes.get(current)?.parentId ?? null
  }

  return ancestors.reverse()
}

/**
 * Resolve a `?comment=` value.
 *
 * Accepts an exact `path` or an `hn_id`, and returns `null` when neither
 * resolves — **a stale link must fall back to the whole thread rather than blank
 * the reader**, because a URL shared before a refetch is the ordinary way to
 * arrive at one. `path` is accepted at all because sibling indices survive a
 * re-ingest better than ids do.
 *
 * **A path is tried first**, because a padded path can also read as an integer:
 * `Number.parseInt('000000.000002')` is `0`. The collision needs an `hn_id` of
 * `0`, which Hacker News has never issued, so this is a precedence rule rather
 * than a live bug — but the order is the kind of thing that silently flips, so it
 * is written down and tested.
 */
export function resolveFocus(
  tree: DiscussionTree,
  ref: string | number | null | undefined,
): number | null {
  if (ref === null || ref === undefined) return null

  const trimmed = String(ref).trim()
  if (trimmed === '') return null

  const byPath = tree.byPath.get(trimmed)
  if (byPath !== undefined) return byPath

  if (/^\d+$/.test(trimmed)) {
    const id = Number.parseInt(trimmed, 10)
    if (tree.nodes.has(id)) return id
  }

  return null
}

// ---------------------------------------------------------------------------
// Matching
// ---------------------------------------------------------------------------

/**
 * Does this comment contain the search term?
 *
 * Reads **`text_plain`, never `text_html`** — which is what stops `q=href` from
 * matching every post containing a link — and is a plain case-insensitive
 * `includes`, matching the backend's `icontains`. That equality is the point: a
 * `q` typed on the thread list and the same `q` on the map must mean one thing.
 *
 * This single predicate feeds both the map's glow and the reader's `<mark>`, so
 * the two views cannot disagree about what matched.
 */
export function matchesSearch(comment: DiscussionComment, term: string): boolean {
  const needle = term.trim().toLowerCase()
  if (needle === '') return false
  return comment.text_plain.toLowerCase().includes(needle)
}

/**
 * Does this comment mention any of the active entity filters?
 *
 * This is the **vendor roll-up**, and this is the only place it exists. It
 * mirrors `discussion_selectors.py`'s
 * `tags__entity__slug__in | tags__entity__vendor__slug__in`, so
 * `?entity=anthropic` lights up a comment tagged only `claude` — a thread that
 * says "Claude" is still an Anthropic thread. Note the asymmetry the backend
 * chose deliberately, and which this reproduces: `claude` does **not** match
 * `claude-code`, whose vendor is `anthropic`.
 */
export function matchesFilters(
  comment: DiscussionComment,
  entities: readonly string[],
): boolean {
  if (entities.length === 0) return false
  return comment.entities.some(
    (entity) =>
      entities.includes(entity.slug) ||
      (entity.vendor !== null && entities.includes(entity.vendor)),
  )
}

// ---------------------------------------------------------------------------
// Collapse
// ---------------------------------------------------------------------------

/**
 * How much of the thread the map opens by default.
 *
 * `roots` and `layer1` bound the *drawn* depth; deeper nodes become a compact
 * bar. `all` opens everything.
 */
export type DepthMode = 'roots' | 'layer1' | 'all'

const DEPTH_LIMIT: Record<DepthMode, number> = {
  roots: 0,
  layer1: 1,
  all: Number.POSITIVE_INFINITY,
}

/**
 * The default depth for a thread of this size.
 *
 * Measured: 71 of 113 stored threads have ≤120 comments, and for those "open
 * everything" is 4-6 screens — genuinely the whole discussion, which is what the
 * reader promises. The rest are up to 1,532 comments with 133 top-level branches,
 * where opening everything is ~84,000px; there the first layer is the honest
 * compromise, and the toolbar says so and offers the other two.
 *
 * A single static rule cannot serve both ends of that range, which is why this is
 * a function of size rather than a constant.
 */
export function defaultDepthMode(commentCount: number): DepthMode {
  return commentCount <= 150 ? 'all' : 'layer1'
}

export interface MapOptions {
  depth: DepthMode
  /** Ids the user collapsed by hand. */
  collapsed: ReadonlySet<number>
  /** Ids the user expanded by hand. Checked first, so it always wins. */
  expanded: ReadonlySet<number>
  /** The focused comment's `hn_id`, from `?comment=`. */
  focusId: number | null
  search: string
  /** Active entity filter slugs. */
  entities: readonly string[]
  /** Drop branches with no match entirely, instead of showing them collapsed. */
  hideQuietBranches: boolean
}

// ---------------------------------------------------------------------------
// Layout
// ---------------------------------------------------------------------------

export type MapRowKind = 'block' | 'compact'

export interface MapRow {
  id: number
  kind: MapRowKind
  comment: DiscussionComment
  /** The drawn depth. */
  depth: number
  x: number
  y: number
  width: number
  height: number
  /** Comments below this row that it stands in for. `0` for a block. */
  hiddenCount: number
  /** How many of those `hiddenCount` comments match the active query. */
  hiddenMatchCount: number
  isOrphan: boolean
  isFocus: boolean
  /** Outside the focus's subtree *and* not one of its ancestors, or filtered out. */
  isDimmed: boolean
  /** Matches the search term — the yellow glow. */
  isHit: boolean
  /** The entities to band the fill with, in legend order. */
  entities: DiscussionEntityRef[]
  /**
   * Every entity named on the block, banded ones first and in band order.
   *
   * Written *on* the block so the map can be read without consulting the legend —
   * and it is the only thing that names the entities past the end of the palette,
   * whose blocks have no hue to carry them. A block with `entities: []` and a
   * non-empty `entityLabels` is exactly that case.
   */
  entityLabels: string[]
  /** Entities mentioned here that are past the end of the palette. */
  uncolouredEntities: number
}

export interface MapLayout {
  /** Ascending by `y`, which is what makes `windowRows` a binary search. */
  rows: MapRow[]
  byId: Map<number, MapRow>
  totalHeight: number
  /** Rows drawn. */
  visibleCount: number
  /** Comments in the thread that the map is not drawing. */
  hiddenTotal: number
  /** Comments matching the active query, drawn or not. */
  matchTotal: number
  rootCount: number
  legend: LegendEntry[]
}

/** The indentation at which blocks stop narrowing, for a given pane width. */
function maxIndentLevels(paneWidth: number): number {
  return Math.max(
    0,
    Math.floor((paneWidth - GUTTER - MIN_BLOCK_WIDTH - RIGHT_PAD) / INDENT),
  )
}

export function layoutMap(
  tree: DiscussionTree,
  options: MapOptions,
  paneWidth: number,
): MapLayout {
  const { order, nodes } = tree
  const hasQuery =
    options.search.trim() !== '' || options.entities.length > 0

  // ---- hues, tallied over the whole thread so a colour means one thing ----
  const commentCounts = new Map<string, number>()
  const mentioned = new Map<string, DiscussionEntityRef>()
  for (const id of order) {
    for (const entity of nodes.get(id)?.comment.entities ?? []) {
      commentCounts.set(entity.slug, (commentCounts.get(entity.slug) ?? 0) + 1)
      if (!mentioned.has(entity.slug)) mentioned.set(entity.slug, entity)
    }
  }
  const legend = buildLegend(mentioned.values(), commentCounts)
  const huePosition = new Map<string, number>()
  legend.forEach((entry, index) => {
    if (entry.hue !== null) huePosition.set(entry.slug, index)
  })

  // ---- matches, folded bottom-up in one reverse pass ----
  const selfMatch = new Map<number, boolean>()
  const subtreeMatch = new Map<number, number>()
  let matchTotal = 0

  for (const id of order) {
    const comment = nodes.get(id)?.comment
    const matched = comment
      ? matchesSearch(comment, options.search) ||
        matchesFilters(comment, options.entities)
      : false
    selfMatch.set(id, matched)
    subtreeMatch.set(id, matched ? 1 : 0)
    if (matched) matchTotal += 1
  }
  for (let index = order.length - 1; index >= 0; index -= 1) {
    const node = nodes.get(order[index]) as DiscussionTreeNode
    if (node.parentId !== null) {
      const parentMatches = subtreeMatch.get(node.parentId) ?? 0
      subtreeMatch.set(node.parentId, parentMatches + (subtreeMatch.get(node.comment.hn_id) ?? 0))
    }
  }

  // ---- the focus spine: always drawn, however the user has collapsed things ----
  const spine = new Set<number>()
  // Everything the reader is *about*: the focus, its ancestors (so the path to it
  // is legible) and its descendants (so the part being read is not greyed out).
  // Dimming is the complement of this set — the "rest of the tree gets dimmed" of
  // the design, expressed once.
  const bright = new Set<number>()
  if (options.focusId !== null && nodes.has(options.focusId)) {
    spine.add(options.focusId)
    for (const ancestor of ancestorIds(tree, options.focusId)) spine.add(ancestor)
    for (const id of subtreeIds(tree, options.focusId)) bright.add(id)
    for (const id of spine) bright.add(id)
  }

  const indentLevels = maxIndentLevels(paneWidth)
  const depthLimit = DEPTH_LIMIT[options.depth]
  const rows: MapRow[] = []
  let y = 0

  /**
   * Decide what to do with one node, without touching the accumulator.
   *
   * `summary` collapses the node *only if it has something to stand in for*. A
   * leaf collapsed by a depth limit or the filter regime is not worth a row: a
   * bar labelled "+0 replies" is a mark that says nothing, and at depth 15 in a
   * large thread there would be thousands of them. Hiding a leaf is the cheaper
   * and more honest outcome, because the whole point of those two rules is to
   * show *less*.
   */
  const decide = (node: DiscussionTreeNode): MapRowKind | 'hidden' => {
    const id = node.comment.hn_id
    const summary = (): MapRowKind | 'hidden' =>
      node.subtreeSize > 1 ? 'compact' : 'hidden'

    // 1. An explicit expansion wins over everything, including a hand-collapse --
    //    an unambiguous rule, and a test pins it so a refactor cannot reverse it.
    if (options.expanded.has(id)) return 'block'
    // 2. The focus and its ancestors are always open, so a deep link can never
    //    point at something the map has hidden.
    if (spine.has(id)) return 'block'
    // 3. An explicit collapse.
    if (options.collapsed.has(id)) return summary()
    // 4. The filter regime: a branch containing no match has nothing to show, so
    //    it costs one thin bar instead of its whole subtree. This is the lever
    //    that turns a 1,532-comment thread into a few dozen rows for a narrow
    //    search.
    if (hasQuery && (subtreeMatch.get(id) ?? 0) === 0) {
      if (options.hideQuietBranches && node.renderDepth === 0) return 'hidden'
      return summary()
    }
    // 5. The browse regime: the drawn depth.
    if (node.renderDepth > depthLimit) return summary()
    return 'block'
  }

  let index = 0
  while (index < order.length) {
    const node = nodes.get(order[index]) as DiscussionTreeNode
    const kind = decide(node)

    // A hidden node contributes nothing at all -- no room, no row -- which is
    // what makes hiding cheaper than showing and lets the rows below slide up.
    if (kind === 'hidden') {
      index += 1
      continue
    }

    const id = node.comment.hn_id
    const depth = Math.min(node.renderDepth, indentLevels)
    const x = GUTTER + depth * INDENT
    const height = kind === 'block' ? blockHeight(node.comment.text_plain.length) : COMPACT_ROW_HEIGHT

    const matched = selfMatch.get(id) ?? false
    const bands: DiscussionEntityRef[] = []
    const uncolouredRefs: DiscussionEntityRef[] = []
    for (const entity of node.comment.entities) {
      if (huePosition.has(entity.slug)) bands.push(entity)
      else uncolouredRefs.push(entity)
    }
    bands.sort(
      (left, right) =>
        (huePosition.get(left.slug) ?? 0) - (huePosition.get(right.slug) ?? 0),
    )
    // Named on the block in the same order the bands are drawn in; anything the
    // palette could not colour follows, alphabetically, so the label is stable.
    uncolouredRefs.sort((left, right) => left.label.localeCompare(right.label))

    const filterHit = matchesFilters(node.comment, options.entities)
    const dimmed =
      (options.focusId !== null && !bright.has(id)) ||
      (options.entities.length > 0 && !filterHit)

    rows.push({
      id,
      kind,
      comment: node.comment,
      depth: node.renderDepth,
      x,
      y,
      width: Math.max(MIN_BLOCK_WIDTH, paneWidth - x - RIGHT_PAD),
      height,
      hiddenCount: kind === 'compact' ? node.subtreeSize - 1 : 0,
      hiddenMatchCount:
        kind === 'compact' ? (subtreeMatch.get(id) ?? 0) - (matched ? 1 : 0) : 0,
      isOrphan: node.isOrphan,
      isFocus: options.focusId === id,
      isDimmed: dimmed,
      isHit: matchesSearch(node.comment, options.search),
      entities: bands,
      entityLabels: [...bands, ...uncolouredRefs].map((entity) => entity.label),
      uncolouredEntities: uncolouredRefs.length,
    })

    y += height + ROW_GAP

    // A compact row stands in for everything below it, and pre-order puts that
    // subtree in the immediately following slice of `order` -- so skipping it is
    // an index jump rather than a second traversal. Without this a collapsed
    // branch would still emit a row per descendant, which is the exact cost the
    // collapse exists to avoid.
    index += kind === 'compact' ? node.subtreeSize : 1
  }

  const totalHeight = rows.length > 0 ? y - ROW_GAP : 0

  return {
    rows,
    byId: new Map(rows.map((row) => [row.id, row])),
    totalHeight,
    visibleCount: rows.length,
    hiddenTotal: order.length - rows.length,
    matchTotal,
    rootCount: tree.roots.length,
    legend,
  }
}

// ---------------------------------------------------------------------------
// Windowing
// ---------------------------------------------------------------------------

export interface RowWindow {
  /** Inclusive. */
  start: number
  /** Exclusive. */
  end: number
}

/**
 * The row to point at for a comment: itself if it is drawn, else its nearest
 * drawn ancestor.
 *
 * This is what makes the map able to follow the reader at all. On a large thread
 * the map opens to the first layer only, so a comment being read three levels
 * down usually has **no row** — and a map that could not follow it would simply
 * stop moving partway through a thread, which reads as broken rather than as
 * collapsed. Falling back to the closest drawn ancestor keeps the map pointed at
 * the branch containing the reader, which is the honest thing to show: the
 * comment is inside that bar.
 *
 * Returns `null` for a comment that is in no drawn row at all, including one that
 * is not in the tree — a stale `?comment=`, or the focus of a thread that has
 * since been refetched.
 */
export function nearestDrawnRow(
  tree: DiscussionTree,
  layout: MapLayout,
  id: number | null,
): number | null {
  if (id === null || !tree.nodes.has(id)) return null
  if (layout.byId.has(id)) return id

  // `ancestorIds` is root-first, so walking it backwards goes nearest-first.
  for (const ancestor of ancestorIds(tree, id).reverse()) {
    if (layout.byId.has(ancestor)) return ancestor
  }
  return null
}

/** Pixels of context kept above and below the viewport, so scrolling is not blank. */
export const WINDOW_OVERSCAN = 400

/**
 * Which rows are worth putting in the DOM.
 *
 * The largest stored thread draws a 22,000px column; this keeps **about twenty
 * rows** in the document at any moment regardless, which is what makes that
 * affordable without a virtualization dependency. `rows` is ascending in `y` by
 * construction, so this is a binary search plus a forward walk.
 */
export function windowRows(
  layout: MapLayout,
  scrollTop: number,
  viewportHeight: number,
  overscan: number = WINDOW_OVERSCAN,
): RowWindow {
  const { rows } = layout
  if (rows.length === 0) return { start: 0, end: 0 }

  const top = Math.max(0, scrollTop - overscan)
  const bottom = scrollTop + viewportHeight + overscan

  let low = 0
  let high = rows.length
  while (low < high) {
    const mid = (low + high) >> 1
    if (rows[mid].y + rows[mid].height < top) low = mid + 1
    else high = mid
  }

  let end = low
  while (end < rows.length && rows[end].y <= bottom) end += 1

  return { start: low, end }
}
