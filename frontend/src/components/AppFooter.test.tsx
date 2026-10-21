import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AppFooter } from './AppFooter'

describe('AppFooter', () => {
  it('puts a GitHub note under the source line', () => {
    render(<AppFooter />)

    const brand = screen.getByText('LLM Picker')
    const sources = screen.getByRole('navigation', { name: 'Sources' })
    const note = screen.getByText((_content, element) =>
      element?.className === 'app-footer__note' &&
      /GitHub, a little star would make our day/i.test(element.textContent ?? ''),
    )
    expect(screen.getByRole('link', { name: 'GitHub' }).getAttribute('href')).toBe(
      'https://github.com/ToothlessOS/llm-picker',
    )
    expect(note.textContent).not.toContain('—')
    expect(
      Boolean(brand.compareDocumentPosition(sources) & Node.DOCUMENT_POSITION_FOLLOWING) &&
      Boolean(sources.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING),
    ).toBe(true)
  })
})
