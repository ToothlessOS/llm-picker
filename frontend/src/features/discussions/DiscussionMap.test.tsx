import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { commentTree, entityRef, vendorRef, type CommentSpec } from '../../test/factories'
import { DiscussionMap } from './DiscussionMap'
import {
  buildDiscussionTree,
  layoutMap,
  windowRows,
  type MapLayout,
  type MapOptions,
} from './discussionTree'

const PANE = 600

function layoutOf(specs: readonly CommentSpec[]): MapLayout {
  const tree = buildDiscussionTree(commentTree(specs))
  const options: MapOptions = {
    depth: 'all',
    collapsed: new Set(),
    expanded: new Set(),
    focusId: null,
    search: '',
    entities: [],
    hideQuietBranches: false,
  }
  return layoutMap(tree, options, PANE)
}

function draw(layout: MapLayout, activeId: number | null = null) {
  const onFocus = vi.fn()
  const onToggle = vi.fn()
  const onGeometry = vi.fn()
  render(
    <DiscussionMap
      activeId={activeId}
      layout={layout}
      onFocus={onFocus}
      onGeometry={onGeometry}
      onToggle={onToggle}
    />,
  )
  return { onFocus, onToggle, onGeometry }
}

function rows(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>('[data-row-id]')]
}

function row(id: number): HTMLElement {
  const found = rows().find((element) => element.dataset.rowId === String(id))
  if (!found) throw new Error(`no map row for comment ${id}`)
  return found
}

describe('DiscussionMap', () => {
  it('places each block from the layout, and sizes it by post length', () => {
    const layout = layoutOf([
      { id: 1, text: 'x'.repeat(51) }, // 31px
      { id: 2, text: 'x'.repeat(5738) }, // capped at 96px
    ])

    draw(layout)

    expect(row(1).style.height).toBe('31px')
    expect(row(1).style.top).toBe('0px')
    expect(row(2).style.top).toBe('33px')
    // A 5,738-character post is 96px, not 570 — the saturation the height scale
    // exists to provide.
    expect(row(2).style.height).toBe('96px')
  })

  it('keeps only the rows in view in the document', () => {
    // The property that makes a 22,000px column affordable. jsdom reports a zero
    // viewport height, so the window is exactly what `windowRows` computes for
    // one — which is what makes this assertion deterministic rather than a guess.
    const layout = layoutOf(
      Array.from({ length: 40 }, (_, index) => ({ id: index + 1, text: 'x'.repeat(191) })),
    )
    const expected = windowRows(layout, 0, 0)

    draw(layout)

    expect(layout.rows).toHaveLength(40)
    expect(rows()).toHaveLength(expected.end - expected.start)
    expect(rows().length).toBeLessThan(20)
    // The far end of the column is genuinely absent, not merely hidden.
    expect(rows().some((element) => element.dataset.rowId === '40')).toBe(false)
  })

  it('bands a block that mentions several entities', () => {
    const layout = layoutOf([
      { id: 1, text: 'about claude and openai', entities: [vendorRef('openai', 'OpenAI'), entityRef()] },
      { id: 2, text: 'about openai', entities: [vendorRef('openai', 'OpenAI')] },
      { id: 3, text: 'about openai', entities: [vendorRef('openai', 'OpenAI')] },
    ])

    draw(layout)

    // Two hues, split evenly, so neither entity looks more important than the other.
    expect(row(1).style.background).toContain('linear-gradient')
    expect(row(1).style.background.match(/var\(--map-hue-/g)).toHaveLength(2)
    expect(row(2).style.background).toBe('var(--map-hue-1)')
  })

  it('marks an entity-less block as neutral rather than colouring it', () => {
    const layout = layoutOf([{ id: 1, text: 'mentions nobody' }])

    draw(layout)

    expect(row(1).classList.contains('map-row--plain')).toBe(true)
    expect(row(1).style.background).toBe('')
  })

  it('selects a block, and expands a collapsed branch when that is what was clicked', () => {
    const layout = layoutOf([
      { id: 1, text: 'alpha', children: [{ id: 2, text: 'beta' }] },
      { id: 3, text: 'gamma' },
    ])
    // The same thread drawn from the top level only. Node 2 is a *branch* here —
    // a leaf would be hidden rather than collapsed, since a bar standing in for
    // nothing says nothing.
    const collapsed = layoutMap(
      buildDiscussionTree(
        commentTree([
          {
            id: 1,
            text: 'alpha',
            children: [{ id: 2, text: 'beta', children: [{ id: 3, text: 'gamma' }] }],
          },
        ]),
      ),
      {
        depth: 'roots',
        collapsed: new Set<number>(),
        expanded: new Set<number>(),
        focusId: null,
        search: '',
        entities: [],
        hideQuietBranches: false,
      },
      PANE,
    )
    const { onFocus, onToggle } = draw(layout)

    fireEvent.click(row(1))
    expect(onFocus).toHaveBeenCalledWith(1)

    render(
      <DiscussionMap
        activeId={null}
        layout={collapsed}
        onFocus={onFocus}
        onGeometry={vi.fn()}
        onToggle={onToggle}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: /\+1 reply/i }))
    expect(onToggle).toHaveBeenCalledWith(2)
  })

  it('says how much a collapsed branch is hiding', () => {
    const layout = layoutMap(
      buildDiscussionTree(
        commentTree([
          {
            id: 1,
            text: 'alpha',
            children: [
              { id: 2, text: 'beta', children: [{ id: 3 }, { id: 4 }] },
            ],
          },
        ]),
      ),
      {
        depth: 'roots',
        collapsed: new Set<number>(),
        expanded: new Set<number>(),
        focusId: null,
        search: '',
        entities: [],
        hideQuietBranches: false,
      },
      PANE,
    )

    draw(layout)

    expect(screen.getByText('+2 replies')).toBeDefined()
  })

  it('describes a block to a screen reader, which cannot see the marks', () => {
    const layout = layoutOf([
      { id: 1, text: 'x'.repeat(191), entities: [entityRef()] },
    ])

    draw(layout)

    const label = row(1).getAttribute('aria-label') ?? ''
    expect(label).toContain('alice')
    expect(label).toContain('depth 0')
    expect(label).toContain('191 characters')
    expect(label).toContain('mentions Claude')
  })

  it('adds the search and selection facts to that description', () => {
    const tree = buildDiscussionTree(
      commentTree([{ id: 1, text: 'about beta' }]),
    )
    const layout = layoutMap(
      tree,
      {
        depth: 'all',
        collapsed: new Set<number>(),
        expanded: new Set<number>(),
        focusId: 1,
        search: 'beta',
        entities: [],
        hideQuietBranches: false,
      },
      PANE,
    )

    draw(layout)

    const label = row(1).getAttribute('aria-label') ?? ''
    expect(label).toContain('matches your search')
    expect(label).toContain('selected')
  })

  it('writes the provider on the block, so the map reads without the legend', () => {
    const layout = layoutOf([
      { id: 1, text: 'about claude', entities: [entityRef()] },
      { id: 2, text: 'mentions nobody' },
    ])

    draw(layout)

    expect(row(1).querySelector('.map-row__name')?.textContent).toBe('Claude')
    // A block that mentions nobody gets no chip — the neutral fill already says so.
    expect(row(2).querySelector('.map-row__name')).toBeNull()
  })

  it('names several providers in the order their bands are drawn', () => {
    const layout = layoutOf([
      { id: 1, text: 'b', entities: [vendorRef('openai', 'OpenAI'), entityRef()] },
      { id: 2, text: 'b', entities: [vendorRef('openai', 'OpenAI')] },
      { id: 3, text: 'b', entities: [vendorRef('openai', 'OpenAI')] },
    ])

    draw(layout)

    // `openai` is mentioned more, so it takes the first band and the first name.
    expect(row(1).querySelector('.map-row__name')?.textContent).toBe('OpenAI · Claude')
  })

  it('names a provider the palette had no hue left for', () => {
    // Sixteen entities over fourteen hues: the last two get no colour at all, so
    // their blocks are drawn neutral and the chip is the only thing that says
    // what they are about. Before this they were indistinguishable from a block
    // that mentioned nobody.
    // One character each, so the blocks are at the floor of the height scale —
    // which also puts the chip on the shortest block it will ever have to fit.
    const layout = layoutOf(
      Array.from({ length: 16 }, (_, index) => ({
        id: index + 1,
        text: 'x',
        entities: [vendorRef(`vendor-${String(index).padStart(2, '0')}`, `Vendor ${index}`)],
      })),
    )

    draw(layout)

    expect(row(16).classList.contains('map-row--plain')).toBe(true)
    expect(row(16).querySelector('.map-row__name')?.textContent).toBe('Vendor 15')
    expect(row(1).querySelector('.map-row__name')?.textContent).toBe('Vendor 0')
  })

  it('hides the chip from a screen reader that already heard the name', () => {
    const layout = layoutOf([{ id: 1, text: 'about claude', entities: [entityRef()] }])

    draw(layout)

    expect(row(1).querySelector('.map-row__name')?.getAttribute('aria-hidden')).toBe('true')
    expect(row(1).getAttribute('aria-label')).toContain('mentions Claude')
  })

  it('marks the row being read', () => {
    const layout = layoutOf([
      { id: 1, text: 'alpha' },
      { id: 2, text: 'beta' },
    ])

    draw(layout, 2)

    expect(row(2).classList.contains('is-reading')).toBe(true)
    expect(row(1).classList.contains('is-reading')).toBe(false)
  })

  it('walks the rows with the arrow keys', () => {
    const layout = layoutOf([
      { id: 1, text: 'alpha' },
      { id: 2, text: 'beta' },
      { id: 3, text: 'gamma' },
    ])

    draw(layout)

    row(1).focus()
    fireEvent.keyDown(row(1), { key: 'ArrowDown' })
    expect(document.activeElement).toBe(row(2))

    fireEvent.keyDown(document.activeElement as HTMLElement, { key: 'ArrowUp' })
    expect(document.activeElement).toBe(row(1))
  })

  it('names every entity in the legend, and flags the ones the palette ran out of', () => {
    const entities = Array.from({ length: 16 }, (_, index) =>
      vendorRef(`vendor-${String(index).padStart(2, '0')}`, `Vendor ${index}`),
    )
    const layout = layoutOf([{ id: 1, text: 'x', entities }])

    draw(layout)

    expect(layout.legend).toHaveLength(16)
    expect(screen.getByText('Vendor 0')).toBeDefined()
    expect(screen.getByText('+2 more uncoloured')).toBeDefined()
    // The two states that are not an entity still get a swatch and a word.
    expect(screen.getByText('no entity')).toBeDefined()
    expect(screen.getByText('search hit')).toBeDefined()
  })

  it('reports its own size, so the layout can be built for it', () => {
    const layout = layoutOf([{ id: 1, text: 'alpha' }])

    const { onGeometry } = draw(layout)

    expect(onGeometry).toHaveBeenCalled()
  })
})
