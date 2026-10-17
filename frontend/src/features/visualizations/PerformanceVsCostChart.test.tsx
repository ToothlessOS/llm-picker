import { fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PerformanceVsCostChart } from './PerformanceVsCostChart'
import { buildScatterModel } from './scatter'

const providers = ['openai', 'anthropic']
const domain: [number, number] = [0.05, 5]
const model = buildScatterModel([
  { key: 'a', name: 'A', organization: 'openai', intelligence: -0.4, cost: 0.1 },
  { key: 'b', name: 'B', organization: 'anthropic', intelligence: 0.2, cost: 1 },
])

describe('PerformanceVsCostChart', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(720)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(340)
  })
  afterEach(() => vi.restoreAllMocks())

  it('retains negative scores and updates focus without rebuilding the SVG', () => {
    const { container, rerender } = render(<PerformanceVsCostChart model={model} variant="interactive"
      scoreLabel="LMArena Agent Score" providers={providers} xDomain={domain} />)
    const point = container.querySelector('circle[data-key="a"]')!
    expect(Number(point.getAttribute('cy'))).toBeGreaterThan(0)
    expect(Number(point.getAttribute('cy'))).toBeLessThan(260)
    rerender(<PerformanceVsCostChart model={model} variant="interactive"
      scoreLabel="LMArena Agent Score" providers={providers} xDomain={domain}
      pinnedKeys={['a']} brushedKeys={[]} />)
    expect(container.querySelector('circle[data-key="a"]')).toBe(point)
    expect(point.classList.contains('is-pinned')).toBe(true)
    expect(container.querySelector('circle[data-key="b"]')!.classList.contains('is-muted')).toBe(true)
  })

  it('uses identical X positions and provider colors in views with different Y values', () => {
    const other = buildScatterModel([
      { key: 'a', name: 'A', organization: 'openai', intelligence: 80, cost: 0.1 },
    ])
    const { container } = render(<>
      <PerformanceVsCostChart model={model} variant="interactive" providers={providers} xDomain={domain} />
      <PerformanceVsCostChart model={other} variant="interactive" providers={providers} xDomain={domain} />
    </>)
    const points = container.querySelectorAll('circle[data-key="a"]')
    expect(points[0].getAttribute('cx')).toBe(points[1].getAttribute('cx'))
    expect(points[0].getAttribute('fill')).toBe(points[1].getAttribute('fill'))
  })

  it('returns model keys from an actual D3 rectangle brush', () => {
    const onBrush = vi.fn()
    const { container } = render(<PerformanceVsCostChart model={model} variant="interactive"
      brushMode onBrush={onBrush} xDomain={domain} />)
    const point = container.querySelector('circle[data-key="a"]')!
    const x = Number(point.getAttribute('cx'))
    const y = Number(point.getAttribute('cy'))
    const overlay = container.querySelector('.performance-brush .overlay')!
    const mouse = (type: string, target: Element | Window, clientX: number, clientY: number) => {
      const event = new MouseEvent(type, { clientX, clientY, bubbles: true, buttons: 1 })
      // jsdom 29's Window proxy cannot be passed through the UIEvent constructor.
      Object.defineProperty(event, 'view', { value: document.defaultView })
      fireEvent(target, event)
    }
    mouse('mousedown', overlay, x - 8, y - 8)
    mouse('mousemove', window, x + 8, y + 8)
    mouse('mouseup', window, x + 8, y + 8)
    expect(onBrush).toHaveBeenLastCalledWith(['a'])
  })
})
