/**
 * Marking the search term inside rendered comment HTML.
 *
 * The temptation is to run a `replace` over `text_html`, and it is wrong: a
 * comment body is an HTML *string*, so a naive pattern happily matches inside
 * `<a href="…/claude/x">` or an attribute value, producing either broken markup
 * or a highlight nobody can see.
 *
 * Instead the HTML is handed to the browser first and only **text nodes** are
 * touched. That is the whole safety argument: `createTreeWalker` with
 * `SHOW_TEXT` yields `Text` nodes and nothing else, and by then the browser has
 * already tokenised the string — tag names, attribute names and attribute values
 * are structurally unreachable rather than merely unlikely to match. There is no
 * hand-rolled HTML scanner here, which is the class of code that gets escaping
 * wrong.
 */

import { useLayoutEffect, type RefObject } from 'react'

/** Containers whose text is not prose and must not be rewritten. */
const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'MARK', 'TEXTAREA'])

export const HIGHLIGHT_CLASS = 'comment-hl'

/**
 * Split one text node around every occurrence of `needle`, back to front.
 *
 * Back to front so earlier offsets stay valid — the alternative is to recompute
 * the search position after every insertion, which is where off-by-one bugs live.
 * Returns how many marks were inserted.
 */
function splitTextNode(node: Text, needle: string): number {
  const haystack = node.data.toLowerCase()
  const pieces: Node[] = []
  let cursor = 0
  let count = 0
  let found = haystack.indexOf(needle)

  while (found !== -1) {
    if (found > cursor) {
      pieces.push(document.createTextNode(node.data.slice(cursor, found)))
    }
    const mark = document.createElement('mark')
    mark.className = HIGHLIGHT_CLASS
    // Sliced from the original, so the marked text keeps its capitalisation.
    mark.textContent = node.data.slice(found, found + needle.length)
    pieces.push(mark)

    count += 1
    cursor = found + needle.length
    found = haystack.indexOf(needle, cursor)
  }

  if (count === 0) return 0
  if (cursor < node.data.length) {
    pieces.push(document.createTextNode(node.data.slice(cursor)))
  }

  const fragment = document.createDocumentFragment()
  for (const piece of pieces) fragment.append(piece)
  node.parentNode?.replaceChild(fragment, node)

  return count
}

/**
 * Wrap every occurrence of `term` in the text under `root`.
 *
 * Matching is a plain case-insensitive `indexOf` — **no `RegExp` is built from
 * user input**, so a search for `.*` or `(` is a literal rather than a pattern.
 * The same predicate as the map's glow (`matchesSearch`, which reads
 * `text_plain`), so the two views cannot disagree about what matched.
 *
 * Returns the number of marks added.
 */
export function applyHighlight(root: HTMLElement, term: string): number {
  const needle = term.trim().toLowerCase()
  // Also guards the loop below: `indexOf('')` returns 0 forever.
  if (needle === '') return 0

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const targets: Text[] = []

  // Collected first, then rewritten: mutating the tree mid-traversal is what
  // makes a `TreeWalker` skip nodes or revisit them.
  for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
    const text = node as Text
    const parent = text.parentElement
    if (parent === null || SKIP_TAGS.has(parent.tagName)) continue
    if (text.data.toLowerCase().includes(needle)) targets.push(text)
  }

  let marks = 0
  for (const target of targets) marks += splitTextNode(target, needle)
  return marks
}

/**
 * Undo `applyHighlight`, merging the split text nodes back together.
 *
 * The `normalize()` is the part that matters: without it, every toggle leaves the
 * text split into more nodes than before, so `q=claude` typed, cleared and typed
 * again would leave the DOM progressively fragmented. It also makes the pass
 * idempotent, which is what stops `<mark><mark>` nesting.
 */
export function clearHighlight(root: HTMLElement): void {
  const marks = root.querySelectorAll(`mark.${HIGHLIGHT_CLASS}`)
  if (marks.length === 0) return

  for (const mark of marks) {
    mark.parentNode?.replaceChild(
      document.createTextNode(mark.textContent ?? ''),
      mark,
    )
  }
  root.normalize()
}

/**
 * Keep a rendered comment marked with the current search term.
 *
 * `useLayoutEffect`, so the marks exist before the browser paints and the text
 * never flashes unmarked. `content` is a dependency alongside `term` because a
 * refetch replaces the subtree through `dangerouslySetInnerHTML`, which discards
 * the marks — passing `text_html` here is what puts them back.
 *
 * React and this effect do not fight: React owns the element and the effect only
 * ever rewrites its children, and React leaves those alone unless `__html`
 * changes.
 */
export function useHighlight(
  ref: RefObject<HTMLElement | null>,
  term: string,
  content: string,
): void {
  useLayoutEffect(() => {
    const element = ref.current
    if (element === null) return

    clearHighlight(element)
    applyHighlight(element, term)
  }, [ref, term, content])
}
