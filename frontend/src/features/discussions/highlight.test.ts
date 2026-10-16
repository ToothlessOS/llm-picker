import { describe, expect, it } from 'vitest'

import { applyHighlight, clearHighlight } from './highlight'

function mount(html: string): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = html
  return root
}

function marks(root: HTMLElement): string[] {
  return [...root.querySelectorAll('mark.comment-hl')].map(
    (mark) => mark.textContent ?? '',
  )
}

describe('applyHighlight', () => {
  it('marks every occurrence and keeps the original capitalisation', () => {
    const root = mount('<p>Claude is good. I use claude daily, and CLAUDE nightly.</p>')

    expect(applyHighlight(root, 'claude')).toBe(3)
    expect(marks(root)).toEqual(['Claude', 'claude', 'CLAUDE'])
    expect(root.textContent).toBe(
      'Claude is good. I use claude daily, and CLAUDE nightly.',
    )
  })

  it('marks inside a link without touching its href', () => {
    // The naive `replace` over the HTML string would corrupt the attribute. The
    // TreeWalker cannot see it at all.
    const root = mount('<p><a href="https://example.com/claude">the docs</a></p>')

    expect(applyHighlight(root, 'claude')).toBe(0)
    expect(root.querySelector('a')?.getAttribute('href')).toBe(
      'https://example.com/claude',
    )

    expect(applyHighlight(root, 'docs')).toBe(1)
    expect(root.querySelector('a')?.getAttribute('href')).toBe(
      'https://example.com/claude',
    )
  })

  it('marks across element boundaries rather than flattening the markup', () => {
    const root = mount('<p>a <b>bold</b> word</p>')

    expect(applyHighlight(root, 'bold')).toBe(1)
    expect(root.querySelector('b')).not.toBeNull()
    expect(root.querySelector('mark')?.parentElement?.tagName).toBe('B')
  })

  it('marks inside a code block, so a glowing block is never a mystery', () => {
    // Deliberately not skipped. The map glows a block because `matchesSearch` hit
    // its text, and `text_plain` does not exclude code — so skipping `<pre>` here
    // would light up a block whose reader shows nothing highlighted.
    const root = mount('<pre><code>pip install claude-cli</code></pre>')

    expect(applyHighlight(root, 'claude')).toBe(1)
  })

  it('ignores script, style and textarea content', () => {
    const root = mount(
      '<p>claude</p><script>var claude = 1</script><style>.claude{}</style>',
    )

    expect(applyHighlight(root, 'claude')).toBe(1)
    expect(marks(root)).toEqual(['claude'])
  })

  it('treats regex metacharacters as literal text', () => {
    const root = mount('<p>it costs $5 (roughly) .*</p>')

    expect(applyHighlight(root, '.*')).toBe(1)
    expect(applyHighlight(root, '($5')).toBe(0)
  })

  it('does nothing for a blank term', () => {
    const root = mount('<p>anything</p>')

    expect(applyHighlight(root, '')).toBe(0)
    expect(applyHighlight(root, '   ')).toBe(0)
    expect(marks(root)).toEqual([])
  })

  it('handles a term at the very start and end of a node', () => {
    const root = mount('<p>claude in the middle claude</p>')

    expect(applyHighlight(root, 'claude')).toBe(2)
    expect(root.textContent).toBe('claude in the middle claude')
  })

  it('marks overlapping candidates independently', () => {
    const root = mount('<p>aa</p><p>aaa</p>')

    expect(applyHighlight(root, 'aa')).toBe(2)
    expect(root.textContent).toBe('aaaaa')
  })
})

describe('clearHighlight', () => {
  it('restores the original text exactly', () => {
    const root = mount('<p>Claude is good. I use claude daily.</p>')
    const before = root.innerHTML

    applyHighlight(root, 'claude')
    clearHighlight(root)

    expect(root.innerHTML).toBe(before)
  })

  it('is idempotent, so toggling a search does not fragment the text', () => {
    // Without the `normalize()` in `clearHighlight`, each pass would leave one
    // more text node behind and repeated searches would build up marks.
    const root = mount('<p>claude and claude again</p>')
    const before = root.innerHTML

    for (let pass = 0; pass < 5; pass += 1) {
      applyHighlight(root, 'claude')
      clearHighlight(root)
    }

    expect(root.innerHTML).toBe(before)
    expect(applyHighlight(root, 'claude')).toBe(2)
  })

  it('survives a changed term without nesting marks', () => {
    const root = mount('<p>claude and gemini</p>')

    applyHighlight(root, 'claude')
    clearHighlight(root)
    expect(applyHighlight(root, 'gemini')).toBe(1)

    expect(marks(root)).toEqual(['gemini'])
    expect(root.querySelectorAll('mark mark')).toHaveLength(0)
  })

  it('does nothing when there is nothing to clear', () => {
    const root = mount('<p>plain</p>')

    clearHighlight(root)

    expect(root.innerHTML).toBe('<p>plain</p>')
  })
})
