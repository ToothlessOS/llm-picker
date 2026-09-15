import { useEffect, useLayoutEffect, useRef } from 'react'
import {
  axisBottom,
  axisLeft,
  scaleBand,
  scaleLinear,
  select,
  type Selection,
} from 'd3'

import {
  formatBarAxisCurrency,
  shortModelName,
  type CostBar,
  type CostBarModel,
  type CostSegmentId,
} from './costBars'

export interface CostPerTaskChartProps {
  model: CostBarModel
  variant: 'preview' | 'interactive'
  hoverKey?: string | null
  pinnedSegment?: CostSegmentId | null
  onHover?: (key: string | null) => void
  onSelect?: (key: string) => void
}

interface ChartTokens {
  text: string
  muted: string
  border: string
  font: string
  segments: Record<CostSegmentId, string>
}

export function CostPerTaskChart({
  model,
  variant,
  hoverKey = null,
  pinnedSegment = null,
  onHover,
  onSelect,
}: CostPerTaskChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const hoverKeyRef = useRef(hoverKey)
  const pinnedSegmentRef = useRef(pinnedSegment)
  const onHoverRef = useRef(onHover)
  const onSelectRef = useRef(onSelect)

  useEffect(() => {
    hoverKeyRef.current = hoverKey
    pinnedSegmentRef.current = pinnedSegment
    onHoverRef.current = onHover
    onSelectRef.current = onSelect
  }, [hoverKey, onHover, onSelect, pinnedSegment])

  useLayoutEffect(() => {
    const node = wrapRef.current
    if (!node) return

    const render = () => {
      const svg = svgRef.current
      if (!svg) return
      const width = node.clientWidth
      const height = node.clientHeight
      if (width < 40 || height < 40 || model.bars.length === 0) return
      drawChart(svg, {
        height,
        model,
        onHover: (key) => onHoverRef.current?.(key),
        onSelect: (key) => onSelectRef.current?.(key),
        variant,
        width,
      })
      applyFocus(svg, hoverKeyRef.current, pinnedSegmentRef.current)
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
  }, [model, variant])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    applyFocus(svg, hoverKey, pinnedSegment)
  }, [hoverKey, pinnedSegment])

  const interactive = variant === 'interactive'

  return (
    <div className={`pareto-chart pareto-chart--${variant}`} ref={wrapRef}>
      <svg
        aria-hidden={interactive ? undefined : true}
        aria-label={
          interactive
            ? 'Stacked bars of cost per Intelligence Index task, attributed by token list-price mix'
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
    model: CostBarModel
    variant: 'preview' | 'interactive'
    onHover?: (key: string | null) => void
    onSelect?: (key: string) => void
  },
) {
  const { width, height, model, variant, onHover, onSelect } = options
  const interactive = variant === 'interactive'
  const tokens = readTokens(svgNode)
  const margin =
    variant === 'preview'
      ? { top: 18, right: 12, bottom: 22, left: 42 }
      : { top: 36, right: 12, bottom: 96, left: 54 }
  const innerWidth = Math.max(width - margin.left - margin.right, 40)
  const innerHeight = Math.max(height - margin.top - margin.bottom, 40)
  const maxCost = Math.max(...model.bars.map((bar) => bar.cost), model.medianCost)
  const y = scaleLinear()
    .domain([0, maxCost * 1.12])
    .nice()
    .range([innerHeight, 0])
  const x = scaleBand<string>()
    .domain(model.bars.map((bar) => bar.key))
    .range([0, innerWidth])
    .paddingInner(0.22)
    .paddingOuter(0.04)
  const yTicks = y.ticks(variant === 'preview' ? 4 : 5)
  const svg = select(svgNode)
  svg.selectAll('*').remove()
  svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
  svg.style('font-family', tokens.font)

  const plot = svg
    .append('g')
    .attr('class', 'cost-plot')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  plot
    .append('g')
    .attr('class', 'cost-grid')
    .selectAll('line')
    .data(yTicks.filter((tick) => tick > 0))
    .join('line')
    .attr('x1', 0)
    .attr('x2', innerWidth)
    .attr('y1', (value) => y(value))
    .attr('y2', (value) => y(value))
    .attr('stroke', tokens.border)
    .attr('stroke-width', 1)

  if (model.medianCost > 0) {
    plot
      .append('line')
      .attr('class', 'cost-median')
      .attr('x1', 0)
      .attr('x2', innerWidth)
      .attr('y1', y(model.medianCost))
      .attr('y2', y(model.medianCost))
      .attr('stroke', tokens.text)
      .attr('stroke-dasharray', '2 4')
      .attr('stroke-width', 1)
      .attr('opacity', 0.45)
    if (interactive) {
      plot
        .append('text')
        .attr('x', 0)
        .attr('y', y(model.medianCost) - 6)
        .attr('text-anchor', 'start')
        .attr('fill', tokens.muted)
        .attr('font-size', 11)
        .text(`Median ${formatBarAxisCurrency(model.medianCost)}`)
    }
  }

  const xAxis = axisBottom(x)
    .tickFormat((key) => {
      const bar = model.bars.find((item) => item.key === key)
      return bar ? shortModelName(bar.name) : key
    })
    .tickSizeOuter(0)
  const yAxis = axisLeft(y)
    .tickValues(yTicks)
    .tickFormat((value) => formatBarAxisCurrency(Number(value)))
    .tickSizeOuter(0)

  const xAxisGroup = plot
    .append('g')
    .attr('transform', `translate(0,${innerHeight})`)
    .call(xAxis)
  styleAxis(xAxisGroup, tokens)
  if (variant === 'preview') {
    xAxisGroup.selectAll('text').remove()
  } else {
    xAxisGroup
      .selectAll('text')
      .attr('transform', 'rotate(-42)')
      .attr('text-anchor', 'end')
      .attr('dx', '-0.4em')
      .attr('dy', '0.25em')
      .attr('font-size', 10)
  }
  styleAxis(plot.append('g').call(yAxis), tokens)

  plot
    .append('text')
    .attr('class', 'pareto-axis-title')
    .attr('transform', 'rotate(-90)')
    .attr('x', -innerHeight / 2)
    .attr('y', variant === 'preview' ? -30 : -40)
    .attr('text-anchor', 'middle')
    .attr('fill', tokens.muted)
    .attr('font-size', variant === 'preview' ? 10 : 12)
    .text(variant === 'preview' ? 'USD / task' : 'Cost per task, USD')

  const groups = plot
    .append('g')
    .attr('class', 'cost-bars')
    .selectAll('g')
    .data(model.bars)
    .join('g')
    .attr('class', 'cost-bar')
    .attr('data-key', (bar) => bar.key)
    .attr('transform', (bar) => `translate(${x(bar.key) ?? 0},0)`)

  groups.each(function (bar) {
    const group = select(this)
    let y0 = 0
    for (const segment of bar.segments) {
      const top = y0 + segment.value
      if (segment.value > 0) {
        group
          .append('rect')
          .attr('class', 'cost-segment')
          .attr('data-segment', segment.id)
          .attr('x', 0)
          .attr('y', y(top))
          .attr('width', x.bandwidth())
          .attr('height', Math.max(y(y0) - y(top), 0))
          .attr('fill', tokens.segments[segment.id])
      }
      y0 = top
    }
  })

  if (interactive) {
    const labels = groups
      .append('text')
      .attr('class', 'cost-total')
      .attr('x', x.bandwidth() / 2)
      .attr('y', (bar) => y(bar.cost) - 6)
      .attr('text-anchor', 'middle')
      .attr('fill', tokens.text)
      .attr('font-size', 10)
      .attr('font-weight', 650)
      .attr('pointer-events', 'none')
      .text((bar) => formatBarAxisCurrency(bar.cost))
    const placed = labels.nodes().map((node, index) => {
      const bar = model.bars[index]
      const width = (node as SVGTextElement).getComputedTextLength()
      return {
        node: node as SVGTextElement,
        left: (x(bar.key) ?? 0) + x.bandwidth() / 2 - width / 2,
        right: (x(bar.key) ?? 0) + x.bandwidth() / 2 + width / 2,
      }
    })
    let lastLeft = Infinity
    for (const item of [...placed].reverse()) {
      if (item.right > lastLeft - 6) {
        select(item.node).remove()
        continue
      }
      lastLeft = item.left
    }
  }

  groups
    .append('rect')
    .attr('class', 'cost-hitbox')
    .attr('x', 0)
    .attr('y', 0)
    .attr('width', x.bandwidth())
    .attr('height', innerHeight)
    .attr('fill', 'transparent')
    .style('pointer-events', interactive ? 'all' : 'none')
    .style('cursor', interactive ? 'pointer' : 'default')
    .on('pointerenter', (_event, bar) => onHover?.(bar.key))
    .on('pointerleave', () => onHover?.(null))
    .on('click', (_event, bar) => onSelect?.(bar.key))
}

function applyFocus(
  svgNode: SVGSVGElement,
  hoverKey: string | null,
  pinnedSegment: CostSegmentId | null,
) {
  const root = select(svgNode)
  root.selectAll<SVGGElement, CostBar>('g.cost-bar').each(function () {
    const node = select(this)
    const key = node.attr('data-key')
    const isActive = hoverKey === key
    node.classed('is-active', isActive)
    node.classed('is-muted', Boolean(hoverKey && !isActive))
  })
  root.selectAll<SVGRectElement, unknown>('rect.cost-segment').each(function () {
    const node = select(this)
    const segment = node.attr('data-segment')
    node.classed(
      'is-segment-muted',
      pinnedSegment !== null && segment !== pinnedSegment,
    )
  })
}

function styleAxis(
  group: Selection<SVGGElement, unknown, null, undefined>,
  tokens: ChartTokens,
) {
  group.select('.domain').attr('stroke', tokens.border)
  group.selectAll('line').attr('stroke', tokens.border)
  group
    .selectAll('text')
    .attr('fill', tokens.muted)
    .attr('font-size', 10)
    .attr('font-family', tokens.font)
}

function readTokens(node: Element): ChartTokens {
  const styles = getComputedStyle(node)
  const rootStyles = getComputedStyle(document.documentElement)
  const token = (name: string) =>
    styles.getPropertyValue(name).trim() || rootStyles.getPropertyValue(name).trim()
  return {
    text: token('--color-text') || '#1a2422',
    muted: token('--color-text-muted') || '#6b736f',
    border: token('--color-border') || '#ddd6cc',
    font: token('--font-sans') || 'DM Sans, sans-serif',
    segments: {
      input: token('--color-cost-input') || '#9bb8b6',
      output: token('--color-cost-output') || '#176b68',
      cacheWrite: token('--color-cost-cache-write') || '#b45a1b',
      cacheHit: token('--color-cost-cache-hit') || '#5c7370',
      unspecified: token('--color-cost-unspecified') || '#c9c0b4',
    },
  }
}