import { useEffect, useLayoutEffect, useRef } from 'react'
import { color as d3Color, interpolateRgb, scaleBand, select } from 'd3'

import { type Category } from '../../api'
import { shortModelName } from './costBars'
import {
  TASK_CATEGORIES,
  TASK_CATEGORY_META,
  rankStrength,
  type RankExtent,
  type TaskCell,
  type TaskFitModel,
  type TaskFitRow,
} from './taskFit'

export interface TaskFitChartProps {
  model: TaskFitModel
  variant: 'preview' | 'interactive'
  hoverKey?: string | null
  sortCategory?: Category
  onHover?: (key: string | null) => void
  onSelect?: (key: string) => void
  onSort?: (category: Category) => void
}

interface ChartTokens {
  text: string
  muted: string
  border: string
  canvas: string
  surface: string
  primary: string
  better: string
  font: string
}

export function TaskFitChart({
  model,
  variant,
  hoverKey = null,
  sortCategory = 'agent',
  onHover,
  onSelect,
  onSort,
}: TaskFitChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const hoverKeyRef = useRef(hoverKey)
  const onHoverRef = useRef(onHover)
  const onSelectRef = useRef(onSelect)
  const onSortRef = useRef(onSort)

  useEffect(() => {
    hoverKeyRef.current = hoverKey
    onHoverRef.current = onHover
    onSelectRef.current = onSelect
    onSortRef.current = onSort
  }, [hoverKey, onHover, onSelect, onSort])

  useLayoutEffect(() => {
    const node = wrapRef.current
    if (!node) return

    const render = () => {
      const svg = svgRef.current
      if (!svg) return
      const width = node.clientWidth
      const height = node.clientHeight
      if (width < 40 || height < 40 || model.rows.length === 0) return
      drawChart(svg, {
        height,
        model,
        onHover: (key) => onHoverRef.current?.(key),
        onSelect: (key) => onSelectRef.current?.(key),
        onSort: (category) => onSortRef.current?.(category),
        sortCategory,
        variant,
        width,
      })
      applyFocus(svg, hoverKeyRef.current)
    }

    render()
    const observer =
      typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(render)
    observer?.observe(node)
    const themeObserver = new MutationObserver(render)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    return () => {
      observer?.disconnect()
      themeObserver.disconnect()
    }
  }, [model, sortCategory, variant])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    applyFocus(svg, hoverKey)
  }, [hoverKey])

  const interactive = variant === 'interactive'

  return (
    <div className={`pareto-chart pareto-chart--${variant}`} ref={wrapRef}>
      <svg
        aria-hidden={interactive ? undefined : true}
        aria-label={
          interactive
            ? 'Heatmap of LMArena ranks across agent, document, search, and webdev'
            : undefined
        }
        ref={svgRef}
        role={interactive ? 'img' : undefined}
      />
    </div>
  )
}

function drawChart(
  svgNode: SVGSVGElement,
  options: {
    width: number
    height: number
    model: TaskFitModel
    variant: 'preview' | 'interactive'
    sortCategory: Category
    onHover?: (key: string | null) => void
    onSelect?: (key: string) => void
    onSort?: (category: Category) => void
  },
) {
  const { width, height, model, variant, sortCategory, onHover, onSelect, onSort } =
    options
  const interactive = variant === 'interactive'
  const tokens = readTokens(svgNode)
  const compact = interactive && width < 720
  const margin = interactive
    ? compact
      ? { top: 28, right: 8, bottom: 8, left: 12 }
      : { top: 32, right: 16, bottom: 10, left: 148 }
    : { top: 22, right: 10, bottom: 8, left: 10 }
  const innerWidth = Math.max(width - margin.left - margin.right, 40)
  const innerHeight = Math.max(height - margin.top - margin.bottom, 40)
  const x = scaleBand<Category>()
    .domain([...TASK_CATEGORIES])
    .range([0, innerWidth])
    .paddingInner(interactive ? 0.1 : 0.08)
    .paddingOuter(0.02)
  const y = scaleBand<string>()
    .domain(model.rows.map((row) => row.key))
    .range([0, innerHeight])
    .paddingInner(interactive ? 0.12 : 0.08)
    .paddingOuter(0.02)
  const svg = select(svgNode)
  svg.selectAll('*').remove()
  svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
  svg.style('font-family', tokens.font)

  const plot = svg
    .append('g')
    .attr('class', 'task-fit-plot')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const headers = plot
    .append('g')
    .attr('class', 'task-fit-headers')
    .selectAll('text')
    .data([...TASK_CATEGORIES])
    .join('text')
    .attr('class', 'task-fit-header')
    .attr('x', (category) => (x(category) ?? 0) + x.bandwidth() / 2)
    .attr('y', -10)
    .attr('text-anchor', 'middle')
    .attr('fill', (category) =>
      category === sortCategory ? tokens.text : tokens.muted,
    )
    .attr('font-size', interactive ? 11 : 9)
    .attr('font-weight', (category) => (category === sortCategory ? 700 : 500))
    .attr('letter-spacing', '0.04em')
    .text((category) =>
      interactive && x.bandwidth() >= 64
        ? TASK_CATEGORY_META[category].label
        : TASK_CATEGORY_META[category].short,
    )

  if (interactive) {
    headers.style('cursor', 'pointer').on('click', (event: PointerEvent, category) => {
      event.stopPropagation()
      onSort?.(category)
    })
  }

  const rowHeight = y.bandwidth()
  const showRank = interactive && rowHeight >= 13 && x.bandwidth() >= 22
  const showNames = interactive && !compact && rowHeight >= 10
  const nameSize = Math.max(8, Math.min(11, rowHeight - 2))
  const nameLimit = 22

  const rows = plot
    .selectAll('g.task-row')
    .data(model.rows)
    .join('g')
    .attr('class', 'task-row')
    .attr('data-key', (row) => row.key)
    .attr('transform', (row) => `translate(0, ${y(row.key) ?? 0})`)

  if (interactive) {
    rows
      .style('cursor', 'pointer')
      .on('pointerenter', (_event, row) => onHover?.(row.key))
      .on('pointerleave', () => onHover?.(null))
      .on('click', (_event, row) => onSelect?.(row.key))
  }

  rows
    .append('rect')
    .attr('class', 'task-row-hit')
    .attr('x', interactive ? -margin.left : 0)
    .attr('width', interactive ? width : innerWidth)
    .attr('height', rowHeight)
    .attr('fill', 'transparent')

  rows.each(function (row) {
    const group = select(this)
    for (const category of TASK_CATEGORIES) {
      const cell = row.cells[category]
      const ranked = cell.evaluated && cell.rank !== null && model.rankExtent[category]
      const fill = ranked
        ? cellFill(cell, model.rankExtent[category], tokens)
        : 'transparent'
      group
        .append('rect')
        .attr('class', 'task-cell')
        .attr('data-category', category)
        .attr('x', x(category) ?? 0)
        .attr('width', x.bandwidth())
        .attr('height', rowHeight)
        .attr('rx', 1)
        .attr('fill', fill)
        .attr('stroke', ranked ? tokens.surface : tokens.border)
        .attr('stroke-width', 1)
      if (showRank && cell.rank !== null && ranked) {
        group
          .append('text')
          .attr('class', 'task-rank')
          .attr('x', (x(category) ?? 0) + x.bandwidth() / 2)
          .attr('y', rowHeight / 2 + 0.5)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'central')
          .attr('fill', rankLabelFill(fill, tokens))
          .attr('font-size', Math.max(8, Math.min(11, rowHeight - 4)))
          .attr('font-variant-numeric', 'tabular-nums')
          .text(String(cell.rank))
      }
    }
  })

  if (showNames) {
    rows
      .append('text')
      .attr('class', 'task-name')
      .attr('x', -10)
      .attr('y', rowHeight / 2 + 0.5)
      .attr('text-anchor', 'end')
      .attr('dominant-baseline', 'central')
      .attr('fill', tokens.text)
      .attr('font-size', nameSize)
      .text((row) => shortModelName(row.name, nameLimit))
  }

  svg
    .on('pointerleave', () => onHover?.(null))
}

function cellFill(
  cell: TaskCell,
  extent: RankExtent | null,
  tokens: ChartTokens,
): string {
  if (!cell.evaluated || cell.rank === null || !extent) return 'transparent'
  const worse = interpolateRgb(tokens.surface, tokens.primary)(0.42)
  return interpolateRgb(worse, tokens.better)(rankStrength(cell.rank, extent))
}

function rankLabelFill(fill: string, tokens: ChartTokens): string {
  const parsed = d3Color(fill)
  if (!parsed) return tokens.text
  const rgb = parsed.rgb()
  const luminance = (0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b) / 255
  return luminance < 0.45 ? tokens.canvas : tokens.text
}

function applyFocus(svg: SVGSVGElement, hoverKey: string | null) {
  select(svg)
    .selectAll<SVGGElement, TaskFitRow>('.task-row')
    .classed('is-muted', (row) => hoverKey !== null && row.key !== hoverKey)
    .classed('is-active', (row) => hoverKey !== null && row.key === hoverKey)
}

function readTokens(node: Element): ChartTokens {
  const styles = getComputedStyle(node)
  const rootStyles = getComputedStyle(document.documentElement)
  const token = (name: string) =>
    styles.getPropertyValue(name).trim() || rootStyles.getPropertyValue(name).trim()
  return {
    better: token('--color-primary-strong') || '#0c4f4d',
    border: token('--color-border-strong') || token('--color-border') || '#c9c0b4',
    canvas: token('--color-bg') || '#f3eee6',
    font: token('--font-sans') || 'DM Sans, sans-serif',
    muted: token('--color-text-muted') || '#6b736f',
    primary: token('--color-primary') || '#176b68',
    surface: token('--color-surface') || '#fbf9f5',
    text: token('--color-text') || '#1a2422',
  }
}
