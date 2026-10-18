import { render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { CategoryBlock } from '../../api'
import { TaskFitChart } from './TaskFitChart'
import { buildTaskFitModel, type TaskFitSource } from './taskFit'

function makeBlock(index: number): CategoryBlock {
  return {
    category: 'agent',
    leaderboard_publish_date: '2026-09-01',
    license: null,
    matched_by_fold: false,
    metric_kind: 'score',
    metric_lower: null,
    metric_upper: null,
    metric_value: 100 - index,
    metric_variance: null,
    model_name: `Model ${index}`,
    organization: 'openai',
    rank: index + 1,
    sample_size: 10,
    session_count: 10,
    source_key: `model-${index}`,
  }
}

function makeModel(count: number) {
  const sources: TaskFitSource[] = Array.from({ length: count }, (_, index) => ({
    categories: {
      agent: makeBlock(index),
      document: null,
      search: null,
      webdev: null,
    },
    key: `model-${index}`,
    name: `Model ${index}`,
    organization: 'openai',
  }))
  return buildTaskFitModel(sources)
}

let width = 886
let height = 513

describe('TaskFitChart', () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(
      () => width,
    )
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(
      () => height,
    )
  })
  afterEach(() => vi.restoreAllMocks())

  it('keeps model names when browser zoom shrinks the row height', () => {
    // 42 rows in a 513 px chart (≈130% zoom) give D3 a ~9.9 px band.
    width = 886
    height = 513
    const { container } = render(
      <TaskFitChart model={makeModel(42)} variant="interactive" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(42)
  })

  it('keeps model names at very high zoom', () => {
    // At 400% zoom the frame clamps to its 420 px minimum (~7.9 px bands).
    width = 415
    height = 418
    const { container } = render(
      <TaskFitChart model={makeModel(42)} variant="interactive" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(42)
  })

  it('renders names unchanged at 100% zoom', () => {
    width = 886
    height = 618
    const { container } = render(
      <TaskFitChart model={makeModel(42)} variant="interactive" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(42)
  })

  it('falls back to compact mode on mobile-width charts', () => {
    width = 327
    height = 420
    const { container } = render(
      <TaskFitChart model={makeModel(42)} variant="interactive" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(0)
    expect(container.querySelectorAll('text.task-fit-header')).toHaveLength(4)
  })

  it('drops names instead of overlapping them in dense datasets', () => {
    width = 886
    height = 418
    const { container } = render(
      <TaskFitChart model={makeModel(100)} variant="interactive" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(0)
  })

  it('never renders names in the preview variant', () => {
    width = 886
    height = 618
    const { container } = render(
      <TaskFitChart model={makeModel(42)} variant="preview" />,
    )
    expect(container.querySelectorAll('text.task-name')).toHaveLength(0)
  })
})
