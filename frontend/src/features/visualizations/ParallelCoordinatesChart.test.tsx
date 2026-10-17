import { fireEvent, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ParallelCoordinatesChart } from './ParallelCoordinatesChart'
import { SPEED_PARALLEL_AXES, type ParallelRecord } from './performanceComparison'

const records: ParallelRecord[] = [
  { key: 'cheap', name: 'Cheap', providerKey: 'xiaomi', cost: 0.1, speed: null, intelligence: 20, coding: 80, agent: 0.1 },
  { key: 'costly', name: 'Costly', providerKey: 'openai', cost: 2, speed: null, intelligence: 50, coding: 30, agent: 0.4 },
]

describe('ParallelCoordinatesChart', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(720)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(340)
  })
  afterEach(() => vi.restoreAllMocks())

  it('places the cheaper model higher on the reversed cost axis', () => {
    const { container } = render(<ParallelCoordinatesChart records={records} costScale="log"
      costDomain={[0.05, 4]} costLabel="Cost" />)
    const cheap = container.querySelector('path[data-key="cheap"]')!
    const costly = container.querySelector('path[data-key="costly"]')!
    const firstY = (path: Element) => Number(path.getAttribute('d')?.match(/M[\d.]+,([\d.]+)/)?.[1])
    expect(firstY(cheap)).toBeLessThan(firstY(costly))
    expect(container.textContent).toContain('cheaper ↑')
    expect(container.textContent).toContain('higher ↑')
  })

  it('reports an inclusive data range from a vertical axis brush', () => {
    const onAxisBrush = vi.fn()
    const { container } = render(<ParallelCoordinatesChart records={records} costScale="log"
      costDomain={[0.05, 4]} costLabel="Cost" onAxisBrush={onAxisBrush} />)
    const overlays = container.querySelectorAll('.parallel-brush .overlay')
    const coding = overlays[2]!
    const mouse = (type: string, target: Element | Window, clientX: number, clientY: number) => {
      const event = new MouseEvent(type, { clientX, clientY, bubbles: true, buttons: 1 })
      Object.defineProperty(event, 'view', { value: document.defaultView })
      fireEvent(target, event)
    }
    const rect = coding.getBoundingClientRect()
    mouse('mousedown', coding, rect.left + 4, rect.top + 8)
    mouse('mousemove', window, rect.left + 4, rect.top + 40)
    mouse('mouseup', window, rect.left + 4, rect.top + 40)
    expect(onAxisBrush).toHaveBeenCalled()
    const [axis, range] = onAxisBrush.mock.lastCall as [string, [number, number]]
    expect(axis).toBe('coding')
    expect(range[0]).toBeLessThanOrEqual(range[1])
  })

  it('places the faster model higher on the output-speed axis', () => {
    const speedRecords: ParallelRecord[] = [
      { key: 'fast', name: 'Fast', providerKey: 'openai', cost: null, speed: 200, intelligence: 40, coding: 40, agent: 0.2 },
      { key: 'slow', name: 'Slow', providerKey: 'openai', cost: null, speed: 20, intelligence: 40, coding: 40, agent: 0.2 },
    ]
    const { container } = render(<ParallelCoordinatesChart records={speedRecords} axes={SPEED_PARALLEL_AXES}
      costScale="linear" costDomain={[0, 250]} costLabel="Output speed" lowerIsBetter={false}
      leadTitle="Output speed" leadHint="faster ↑" />)
    const firstY = (path: Element) => Number(path.getAttribute('d')?.match(/M[\d.]+,([\d.]+)/)?.[1])
    const fast = container.querySelector('path[data-key="fast"]')!
    const slow = container.querySelector('path[data-key="slow"]')!
    expect(firstY(fast)).toBeLessThan(firstY(slow))
    expect(container.textContent).toContain('faster ↑')
    expect(container.textContent).toContain('Output speed')
  })
})
