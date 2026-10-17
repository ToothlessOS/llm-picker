import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { OverviewRow } from '../../api'
import { PerformanceVsCostPage } from './PerformanceVsCostPage'
import type { PerformanceVsCostChartProps } from './PerformanceVsCostChart'

vi.mock('./PerformanceVsCostChart', () => ({
  PerformanceVsCostChart: (props: PerformanceVsCostChartProps) => (
    <div data-testid={props.scoreLabel} data-pinned={props.pinnedKeys?.join(',')}
      data-hover={props.hoverKey ?? ''} data-brushed={props.brushedKeys?.join(',') ?? 'none'}
      data-domain={props.xDomain?.join(',')} data-scale={props.costScale}
      data-providers={props.providers?.join(',')}>
      <button onClick={() => props.onBrush?.(['mid'])}>Brush {props.scoreLabel}</button>
      <button onClick={() => props.onBrush?.([])}>Empty brush {props.scoreLabel}</button>
      <button onClick={() => props.onSelect?.('mid')}>Pick {props.scoreLabel}</button>
    </div>
  ),
}))

const makeRow = vi.hoisted(() => {
  return function makeRow(input: {
    key: string
    name: string
    organization: string
    intelligence: number | null
    cost: number | null
    outputSpeed?: number | null
    latency?: number | null
  }): OverviewRow {
    return {
      model: {
        key: input.key,
        name: input.name,
        organization: input.organization,
        license: null,
        in_agent_set: true,
      },
      categories: {
        agent: {
          category: 'agent',
          metric_kind: 'score',
          metric_value: 0.1,
          metric_lower: null,
          metric_upper: null,
          metric_variance: null,
          sample_size: 10,
          session_count: 10,
          rank: 1,
          model_name: input.name,
          organization: input.organization,
          license: null,
          leaderboard_publish_date: '2026-09-01',
          source_key: input.key,
          matched_by_fold: false,
        },
        document: null,
        search: null,
        webdev: null,
      },
      aa: {
        id: input.key,
        slug: input.key,
        name: input.name,
        creator: { id: input.organization, name: input.organization },
        release_date: null,
        intelligence_index_version: 1,
        intelligence_index: input.intelligence,
        coding_index: input.key === 'expensive-weak' ? null : 60,
        agentic_index: null,
        intelligence_index_total_cost: null,
        cost_per_task: input.cost,
        pricing: {
          price_1m_input_tokens: input.key === 'cheap-weak' ? 0 : 5,
          price_1m_output_tokens: 10,
          price_1m_cache_hit_tokens: null,
          price_1m_cache_write_tokens: null,
        },
        performance: {
          median_output_tokens_per_second: input.outputSpeed === undefined ? 80 : input.outputSpeed,
          median_time_to_first_token_seconds: input.latency === undefined ? 2 : input.latency,
          median_time_to_first_answer_token_seconds: null,
          median_end_to_end_response_time_seconds: null,
        },
        is_retained: true,
        last_synced_at: '2026-09-15T00:00:00Z',
      },
      match: {
        method: 'exact_key',
        confidence: 1,
        is_manual: false,
        matched_key: input.key,
        last_matched_at: '2026-09-15T00:00:00Z',
      },
    }
  }
})

vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>()
  return {
    ...actual,
    getOverview: vi.fn().mockResolvedValue({
      count: 3,
      next: null,
      previous: null,
      page_size: 200,
      results: [
        makeRow({
          key: 'cheap-weak',
          name: 'Cheap weak',
          organization: 'xiaomi',
          intelligence: 20,
          cost: 0.1,
        }),
        makeRow({
          key: 'mid',
          name: 'Balanced',
          organization: 'openai',
          intelligence: 40,
          cost: 0.5,
          outputSpeed: 100,
          latency: 1,
        }),
        makeRow({
          key: 'expensive-weak',
          name: 'Expensive weak',
          organization: 'google',
          intelligence: 25,
          cost: 2,
        }),
        makeRow({ key: 'fourth', name: 'Fourth', organization: 'openai', intelligence: 30, cost: 1,
          outputSpeed: null, latency: null }),
      ],
      meta: {
        generated_at: '2026-09-15T00:00:00Z',
        sources: {},
        categories_included: [],
      },
    }),
  }
})

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PerformanceVsCostPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('PerformanceVsCostPage', () => {
  it('keeps one scatter as the entry and shares it with parallel coordinates', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Parallel coordinates' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Performance explorer' })).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Performance vs. cost', selected: true })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'AA Intelligence Index' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'AA Coding Index' })).toBeNull()
    const cheap = await screen.findByRole('button', { name: 'Pin Cheap weak' })
    await user.hover(cheap)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Cheap weak' })).toBeTruthy()
    })
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-hover')).toBe('cheap-weak')
    await user.click(cheap)
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('cheap-weak')
    expect(screen.getByRole('link', { name: 'Model page' }).getAttribute('href')).toBe('/models/cheap-weak')
    await user.selectOptions(screen.getByLabelText('Performance'), 'coding')
    expect(screen.getByRole('heading', { name: 'AA Coding Index' })).toBeTruthy()
    expect(screen.queryByRole('heading', { name: 'AA Intelligence Index' })).toBeNull()
    expect(screen.getByTestId('AA Coding Index').getAttribute('data-pinned')).toBe('cheap-weak')
  })

  it('restores the three scatter views and coordinates brushing across them', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('button', { name: 'Pin Balanced' })
    await user.click(screen.getByRole('radio', { name: 'Compare views' }))
    const labels = ['AA Intelligence Index', 'AA Coding Index', 'LMArena Agent Score']
    for (const label of labels) expect(screen.getByRole('heading', { name: label })).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Brush AA Coding Index' }))
    for (const label of labels) expect(screen.getByTestId(label).getAttribute('data-brushed')).toBe('mid')
    expect(new Set(labels.map((label) => screen.getByTestId(label).getAttribute('data-domain'))).size).toBe(1)
    expect(screen.queryByRole('button', { name: 'Pin Cheap weak' })).toBeNull()
    expect(screen.getByText(/1 models match the scatter brush/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Empty brush AA Coding Index' }))
    expect(screen.queryByRole('button', { name: 'Pin Balanced' })).toBeNull()
    expect(screen.getByText(/0 models match the scatter brush/)).toBeTruthy()
    await user.click(screen.getByRole('button', { name: 'Clear brush' }))
    expect(screen.getByRole('button', { name: 'Pin Cheap weak' })).toBeTruthy()
  })

  it('changes costs, scales, providers and visibility without dropping pinned models', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Pin Cheap weak' }))
    await user.selectOptions(screen.getByLabelText('Cost reference'), 'input')
    expect(screen.queryByRole('button', { name: 'Pin Cheap weak' })).toBeNull()
    await user.click(screen.getByRole('radio', { name: 'Linear' }))
    expect(screen.getByRole('button', { name: 'Pin Cheap weak' })).toBeTruthy()
    await user.selectOptions(screen.getByLabelText('Provider'), 'openai')
    expect(screen.queryByRole('button', { name: 'Pin Cheap weak' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Cheap weak' })).toBeTruthy()
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('cheap-weak')
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-scale')).toBe('linear')
    await user.click(screen.getByRole('radio', { name: 'Compare views' }))
    await user.click(screen.getByRole('checkbox', { name: 'AA Coding Index' }))
    expect(screen.queryByRole('heading', { name: 'AA Coding Index' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'AA Intelligence Index' })).toBeTruthy()
  })

  it('caps the comparison at three models and clears shared selections', async () => {
    const user = userEvent.setup()
    renderPage()
    for (const name of ['Cheap weak', 'Balanced', 'Expensive weak']) {
      await user.click(await screen.findByRole('button', { name: `Pin ${name}` }))
    }
    await user.click(screen.getByRole('button', { name: 'Pin Fourth' }))
    expect(screen.getByText(/Comparison is full/)).toBeTruthy()
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('cheap-weak,mid,expensive-weak')
    await user.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(screen.queryByRole('region', { name: 'Pinned model comparison' })).toBeNull()
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('')
  })

  it('switches to a speed scatter and keeps pinned models', async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Pin Cheap weak' }))
    await user.click(screen.getByRole('tab', { name: 'Performance vs. speed' }))
    expect(screen.getByRole('heading', { name: 'Output speed (tokens/sec)' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Parallel coordinates' })).toBeTruthy()
    expect(screen.getByRole('heading', { name: 'Rank comparison' })).toBeTruthy()
    expect(screen.getByText(/a higher position is faster/)).toBeTruthy()
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('cheap-weak')
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-scale')).toBe('linear')
    await user.selectOptions(screen.getByLabelText('Speed measure'), 'ttft')
    expect(screen.getByRole('heading', { name: 'Time to first token (seconds)' })).toBeTruthy()
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-scale')).toBe('log')
    expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-pinned')).toBe('cheap-weak')
  })

  it('links real parallel-axis brushes to output speed and first-token latency', async () => {
    const width = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(720)
    const height = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(340)
    const user = userEvent.setup()
    const page = renderPage()
    const brushLeadAxis = (top: number, bottom: number) => {
      const overlay = page.container.querySelector('.parallel-brush .overlay')!
      const mouse = (type: string, target: Element | Window, clientY: number) => {
        const event = new MouseEvent(type, { clientX: 0, clientY, bubbles: true, buttons: 1 })
        Object.defineProperty(event, 'view', { value: document.defaultView })
        fireEvent(target, event)
      }
      mouse('mousedown', overlay, top)
      mouse('mousemove', window, bottom)
      mouse('mouseup', window, bottom)
    }

    try {
      await screen.findByRole('button', { name: 'Pin Balanced' })
      await user.click(screen.getByRole('tab', { name: 'Performance vs. speed' }))
      expect(screen.queryByRole('button', { name: 'Pin Fourth' })).toBeNull()

      // A band near the top of the output-speed axis contains 100, but not 80 tok/s.
      brushLeadAxis(8, 40)
      expect(screen.getByRole('button', { name: 'Pin Balanced' })).toBeTruthy()
      expect(screen.queryByRole('button', { name: 'Pin Cheap weak' })).toBeNull()
      expect(screen.getByText('1 models match Speed')).toBeTruthy()
      expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-brushed')).toBe('mid')

      await user.click(screen.getByRole('button', { name: 'Clear brush' }))
      expect(screen.getByRole('button', { name: 'Pin Cheap weak' })).toBeTruthy()
      await user.selectOptions(screen.getByLabelText('Speed measure'), 'ttft')

      // On the reversed log-latency axis this band contains 1, but not 2 seconds.
      brushLeadAxis(50, 80)
      expect(screen.getByRole('button', { name: 'Pin Balanced' })).toBeTruthy()
      expect(screen.queryByRole('button', { name: 'Pin Cheap weak' })).toBeNull()
      expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-brushed')).toBe('mid')

      await user.click(screen.getByRole('tab', { name: 'Performance vs. cost' }))
      expect(screen.getByRole('button', { name: 'Pin Fourth' })).toBeTruthy()
      expect(screen.getByTestId('AA Intelligence Index').getAttribute('data-brushed')).toBe('none')
    } finally {
      page.unmount()
      width.mockRestore()
      height.mockRestore()
    }
  })
})
