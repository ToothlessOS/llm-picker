import { useEffect, useLayoutEffect, useRef } from 'react'
import {
  axisBottom,
  axisLeft,
  curveMonotoneX,
  Delaunay,
  line,
  pointer,
  scaleLinear,
  scaleLog,
  select,
  ticks,
  type Selection,
} from 'd3'

import {
  formatAxisCurrency,
  LOG_COST_TICKS,
  providerColor,
  type ScatterModel,
  type ScatterPoint,
} from './scatter'

export interface PerformanceVsCostChartProps {
  model: ScatterModel
  variant: 'preview' | 'interactive'
  hoverKey?: string | null
  pinnedProvider?: string | null
  onHover?: (key: string | null) => void
  onSelect?: (key: string) => void
}

interface ChartTokens {
  text: string
  muted: string
  border: string
  primary: string
  surface: string
  font: string
}

interface PlotFrame {
  x: (value: number) => number
  y: (value: number) => number
  innerWidth: number
  innerHeight: number
  points: ScatterPoint[]
}

interface LabelBox {
  x: number
  y: number
  width: number
  height: number
}

export function PerformanceVsCostChart({
  model,
  variant,
  hoverKey = null,
  pinnedProvider = null,
  onHover,
  onSelect,
}: PerformanceVsCostChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const frameRef = useRef<PlotFrame | null>(null)
  const hoverKeyRef = useRef(hoverKey)
  const pinnedProviderRef = useRef(pinnedProvider)
  const onHoverRef = useRef(onHover)
  const onSelectRef = useRef(onSelect)

  useEffect(() => {
    hoverKeyRef.current = hoverKey
    pinnedProviderRef.current = pinnedProvider
    onHoverRef.current = onHover
    onSelectRef.current = onSelect
  }, [hoverKey, onHover, onSelect, pinnedProvider])

  useLayoutEffect(() => {
    const node = wrapRef.current
    if (!node) return

    const render = () => {
      const svg = svgRef.current
      if (!svg) return
      const width = node.clientWidth
      const height = node.clientHeight
      if (width < 40 || height < 40 || model.points.length === 0) return
      drawChart(svg, {
        height,
        model,
        onHover: (key) => onHoverRef.current?.(key),
        onSelect: (key) => onSelectRef.current?.(key),
        variant,
        width,
      })
      frameRef.current = readFrame(svg)
      applyFocus(svg, frameRef.current, hoverKeyRef.current, pinnedProviderRef.current)
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
    if (!svg || !frameRef.current) return
    applyFocus(svg, frameRef.current, hoverKey, pinnedProvider)
  }, [hoverKey, pinnedProvider])

  const interactive = variant === 'interactive'

  return (
    <div className={`pareto-chart pareto-chart--${variant}`} ref={wrapRef}>
      <svg
        aria-hidden={interactive ? undefined : true}
        aria-label={
          interactive
            ? 'Scatter plot of intelligence index versus cost per task, with a Pareto front and most attractive quadrant'
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
    model: ScatterModel
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
      ? { top: 18, right: 16, bottom: 36, left: 42 }
      : { top: 22, right: 132, bottom: 52, left: 58 }
  const innerWidth = Math.max(width - margin.left - margin.right, 40)
  const innerHeight = Math.max(height - margin.top - margin.bottom, 40)
  const costs = model.points.map((point) => point.cost)
  const scores = model.points.map((point) => point.intelligence)
  const x = scaleLog()
    .domain(paddedLogDomain(costs))
    .range([0, innerWidth])
  const y = scaleLinear()
    .domain(paddedLinearDomain(scores))
    .range([innerHeight, 0])
  const xTicks = LOG_COST_TICKS.filter(
    (tick) => tick >= x.domain()[0] && tick <= x.domain()[1],
  )
  const yTicks = ticks(y.domain()[0], y.domain()[1], variant === 'preview' ? 4 : 6)
  const providers = model.points.map((point) => point.providerKey)
  const svg = select(svgNode)
  svg.selectAll('*').remove()
  svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
  svg.style('font-family', tokens.font)

  const plot = svg
    .append('g')
    .attr('class', 'pareto-plot')
    .attr('transform', `translate(${margin.left},${margin.top})`)

  const medianX = x(model.medianCost)
  const medianY = y(model.medianIntelligence)
  const quadrantWidth = Math.max(medianX, 0)
  const quadrantHeight = Math.max(medianY, 0)
  if (quadrantWidth > 8 && innerHeight - quadrantHeight > 8) {
    plot
      .append('rect')
      .attr('class', 'pareto-quadrant')
      .attr('x', 0)
      .attr('y', 0)
      .attr('width', quadrantWidth)
      .attr('height', medianY)
      .attr('fill', tokens.primary)
      .attr('fill-opacity', 0.12)
    if (quadrantWidth > 72 && medianY > 28) {
      plot
        .append('text')
        .attr('class', 'pareto-quadrant-label')
        .attr('x', 8)
        .attr('y', 16)
        .attr('fill', tokens.primary)
        .attr('font-size', variant === 'preview' ? 9 : 11)
        .attr('font-weight', 650)
        .attr('letter-spacing', '0.04em')
        .text('Most attractive')
    }
  }

  plot
    .append('g')
    .attr('class', 'pareto-grid')
    .selectAll('line')
    .data(yTicks)
    .join('line')
    .attr('x1', 0)
    .attr('x2', innerWidth)
    .attr('y1', (value) => y(value))
    .attr('y2', (value) => y(value))
    .attr('stroke', tokens.border)
    .attr('stroke-width', 1)

  if (interactive) {
    plot
      .append('g')
      .attr('class', 'pareto-grid')
      .selectAll('line')
      .data(xTicks)
      .join('line')
      .attr('x1', (value) => x(value))
      .attr('x2', (value) => x(value))
      .attr('y1', 0)
      .attr('y2', innerHeight)
      .attr('stroke', tokens.border)
      .attr('stroke-width', 1)
  }

  const xAxis = axisBottom(x)
    .tickValues(xTicks.map((tick) => tick))
    .tickFormat((value) => formatAxisCurrency(Number(value)))
    .tickSizeOuter(0)
  const yAxis = axisLeft(y)
    .tickValues(yTicks)
    .tickFormat((value) => String(Number(value)))
    .tickSizeOuter(0)

  const xAxisGroup = plot
    .append('g')
    .attr('transform', `translate(0,${innerHeight})`)
    .call(xAxis)
  const yAxisGroup = plot.append('g').call(yAxis)
  styleAxis(xAxisGroup, tokens)
  styleAxis(yAxisGroup, tokens)

  plot
    .append('text')
    .attr('class', 'pareto-axis-title')
    .attr('x', innerWidth / 2)
    .attr('y', innerHeight + (variant === 'preview' ? 28 : 40))
    .attr('text-anchor', 'middle')
    .attr('fill', tokens.muted)
    .attr('font-size', variant === 'preview' ? 10 : 12)
    .text(variant === 'preview' ? 'Cost / task (log)' : 'Cost per task, USD (log scale)')

  plot
    .append('text')
    .attr('class', 'pareto-axis-title')
    .attr('transform', 'rotate(-90)')
    .attr('x', -innerHeight / 2)
    .attr('y', variant === 'preview' ? -30 : -42)
    .attr('text-anchor', 'middle')
    .attr('fill', tokens.muted)
    .attr('font-size', variant === 'preview' ? 10 : 12)
    .text(variant === 'preview' ? 'Intelligence' : 'Intelligence index')

  const paretoLine = line<ScatterPoint>()
    .x((point) => x(point.cost))
    .y((point) => y(point.intelligence))
    .curve(curveMonotoneX)

  plot
    .append('path')
    .attr('class', 'pareto-front-line')
    .attr('d', paretoLine(model.pareto) ?? '')
    .attr('fill', 'none')
    .attr('stroke', tokens.text)
    .attr('stroke-width', 1.5)
    .attr('stroke-dasharray', '1.5 3.5')
    .attr('opacity', 0.72)

  plot
    .append('line')
    .attr('class', 'pareto-hair pareto-hair-x')
    .attr('stroke', tokens.muted)
    .attr('stroke-dasharray', '2 3')
    .attr('opacity', 0)
  plot
    .append('line')
    .attr('class', 'pareto-hair pareto-hair-y')
    .attr('stroke', tokens.muted)
    .attr('stroke-dasharray', '2 3')
    .attr('opacity', 0)

  const radius = (point: ScatterPoint) => {
    if (variant === 'preview') return point.onPareto ? 5.5 : 4
    return point.onPareto ? 7.5 : 5.5
  }

  plot
    .append('g')
    .attr('class', 'pareto-points')
    .selectAll('circle')
    .data(model.points)
    .join('circle')
    .attr('class', 'pareto-dot')
    .attr('data-key', (point) => point.key)
    .attr('data-provider', (point) => point.providerKey)
    .attr('data-r', (point) => radius(point))
    .attr('cx', (point) => x(point.cost))
    .attr('cy', (point) => y(point.intelligence))
    .attr('r', (point) => radius(point))
    .attr(
      'fill',
      (point) =>
        variant === 'preview' ? tokens.primary : providerColor(point.providerKey, providers),
    )
    .attr('stroke', (point) => (point.onPareto ? tokens.text : tokens.surface))
    .attr('stroke-width', (point) => (point.onPareto ? 1.6 : 1.2))

  if (interactive) {
    const labels = layoutLabels(model.pareto, x, y, innerWidth)
    plot
      .append('g')
      .attr('class', 'pareto-labels')
      .selectAll('text')
      .data(labels)
      .join('text')
      .attr('class', 'pareto-label')
      .attr('data-key', (label) => label.point.key)
      .attr('x', (label) => label.x)
      .attr('y', (label) => label.y)
      .attr('text-anchor', (label) => label.anchor)
      .attr('fill', tokens.text)
      .attr('font-size', 11)
      .attr('font-weight', 600)
      .text((label) => label.point.name)
  }

  const hitbox = plot
    .append('rect')
    .attr('class', 'pareto-hitbox')
    .attr('width', innerWidth)
    .attr('height', innerHeight)
    .attr('fill', 'transparent')
    .style('pointer-events', interactive ? 'all' : 'none')

  if (interactive) {
    const delaunay = Delaunay.from(
      model.points,
      (point) => x(point.cost),
      (point) => y(point.intelligence),
    )
    const nearestKey = (event: PointerEvent) => {
      const [mx, my] = pointer(event)
      const index = delaunay.find(mx, my)
      const point = model.points[index]
      if (!point) return null
      const distance = Math.hypot(x(point.cost) - mx, y(point.intelligence) - my)
      return distance <= 52 ? point.key : null
    }

    hitbox
      .on('pointermove', (event: PointerEvent) => {
        const key = nearestKey(event)
        hitbox.style('cursor', key ? 'pointer' : 'default')
        onHover?.(key)
      })
      .on('pointerleave', () => onHover?.(null))
      .on('click', (event: PointerEvent) => {
        const key = nearestKey(event)
        if (key) onSelect?.(key)
      })
  }

  svg.datum({ x, y, innerWidth, innerHeight, points: model.points } satisfies PlotFrame)
}

function readFrame(svgNode: SVGSVGElement): PlotFrame | null {
  return (select(svgNode).datum() as PlotFrame | undefined) ?? null
}

function applyFocus(
  svgNode: SVGSVGElement,
  frame: PlotFrame | null,
  hoverKey: string | null,
  pinnedProvider: string | null,
) {
  if (!frame) return
  const root = select(svgNode)
  root.selectAll<SVGCircleElement, ScatterPoint>('circle.pareto-dot').each(function () {
    const node = select(this)
    const key = node.attr('data-key')
    const provider = node.attr('data-provider')
    const isActive = hoverKey === key
    const isPinnedOut =
      pinnedProvider !== null && provider !== pinnedProvider && !isActive
    const isMuted = Boolean(hoverKey && !isActive) || isPinnedOut
    const baseRadius = Number(node.attr('data-r'))
    node.classed('is-active', isActive)
    node.classed('is-muted', isMuted)
    node.attr('r', isActive ? baseRadius + 2.2 : baseRadius)
  })
  root.selectAll<SVGTextElement, unknown>('text.pareto-label').each(function () {
    const node = select(this)
    const key = node.attr('data-key')
    node.classed('is-active', hoverKey === key)
    node.classed('is-muted', Boolean(hoverKey && hoverKey !== key))
  })

  const active = frame.points.find((point) => point.key === hoverKey)
  const hairX = root.select('.pareto-hair-x')
  const hairY = root.select('.pareto-hair-y')
  if (!active) {
    hairX.attr('opacity', 0)
    hairY.attr('opacity', 0)
    return
  }
  const px = frame.x(active.cost)
  const py = frame.y(active.intelligence)
  hairX
    .attr('x1', 0)
    .attr('x2', px)
    .attr('y1', py)
    .attr('y2', py)
    .attr('opacity', 0.9)
  hairY
    .attr('x1', px)
    .attr('x2', px)
    .attr('y1', frame.innerHeight)
    .attr('y2', py)
    .attr('opacity', 0.9)
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
  const token = (name: string) => {
    const fromNode = styles.getPropertyValue(name).trim()
    if (fromNode) return fromNode
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  }
  return {
    text: token('--color-text') || '#1a2422',
    muted: token('--color-text-muted') || '#6b736f',
    border: token('--color-border') || '#ddd6cc',
    primary: token('--color-primary') || '#176b68',
    surface: token('--color-surface') || '#fbf9f5',
    font: token('--font-sans') || 'DM Sans, sans-serif',
  }
}

function paddedLogDomain(values: readonly number[]): [number, number] {
  const min = Math.min(...values)
  const max = Math.max(...values)
  if (min === max) return [min / 2, max * 2]
  return [min * 0.82, max * 1.22]
}

function paddedLinearDomain(values: readonly number[]): [number, number] {
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 10
  return [Math.max(0, min - span * 0.14), max + span * 0.16]
}

function layoutLabels(
  points: readonly ScatterPoint[],
  x: (value: number) => number,
  y: (value: number) => number,
  innerWidth: number,
) {
  const placed: LabelBox[] = []
  return points.map((point) => {
    const px = x(point.cost)
    const py = y(point.intelligence)
    const width = Math.min(point.name.length * 6.3 + 4, 168)
    const height = 14
    const preferEnd = px > innerWidth * 0.58
    const anchor: 'start' | 'end' = preferEnd ? 'end' : 'start'
    let lx = preferEnd ? px - 10 : px + 10
    let ly = py - 8
    const box = (): LabelBox => ({
      x: anchor === 'start' ? lx : lx - width,
      y: ly - height,
      width,
      height,
    })
    let attempts = 0
    while (placed.some((other) => overlaps(box(), other)) && attempts < 10) {
      ly -= 12
      attempts += 1
    }
    placed.push(box())
    return { point, x: lx, y: ly, anchor }
  })
}

function overlaps(left: LabelBox, right: LabelBox): boolean {
  return !(
    left.x + left.width < right.x ||
    right.x + right.width < left.x ||
    left.y + left.height < right.y ||
    right.y + right.height < left.y
  )
}
