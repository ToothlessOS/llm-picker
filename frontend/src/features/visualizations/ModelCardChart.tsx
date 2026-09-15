import { useEffect, useLayoutEffect, useRef } from 'react'
import { scaleLinear, select, type Selection } from 'd3'

import {
  RADAR_AXES,
  RADAR_AXIS_META,
  isCompleteCard,
  type ModelCard,
  type RadarAxisId,
} from './modelCard'

export interface ModelCardChartProps {
  card: ModelCard
  compare?: ModelCard | null
  variant: 'preview' | 'interactive'
  hoverAxis?: RadarAxisId | null
  onHoverAxis?: (axis: RadarAxisId | null) => void
}

interface ChartTokens {
  text: string
  muted: string
  border: string
  primary: string
  primaryStrong: string
  surface: string
  font: string
}

interface RadarPoint {
  axis: RadarAxisId
  angle: number
  measured: boolean
  percentile: number | null
  x: number
  y: number
  hitX: number
  hitY: number
}

const GRID_TICKS = [0.25, 0.5, 0.75, 1]

export function ModelCardChart({
  card,
  compare = null,
  variant,
  hoverAxis = null,
  onHoverAxis,
}: ModelCardChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const hoverAxisRef = useRef(hoverAxis)
  const onHoverAxisRef = useRef(onHoverAxis)

  useEffect(() => {
    hoverAxisRef.current = hoverAxis
    onHoverAxisRef.current = onHoverAxis
  }, [hoverAxis, onHoverAxis])

  useLayoutEffect(() => {
    const node = wrapRef.current
    if (!node) return

    const render = () => {
      const svg = svgRef.current
      if (!svg) return
      const width = node.clientWidth
      const height = node.clientHeight
      if (width < 40 || height < 40) return
      drawChart(svg, {
        card,
        compare,
        height,
        onHoverAxis: (axis) => onHoverAxisRef.current?.(axis),
        variant,
        width,
      })
      applyFocus(svg, hoverAxisRef.current)
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
  }, [card, compare, variant])

  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    applyFocus(svg, hoverAxis)
  }, [hoverAxis])

  const interactive = variant === 'interactive'

  return (
    <div className={`pareto-chart pareto-chart--${variant}`} ref={wrapRef}>
      <svg
        aria-hidden={interactive ? undefined : true}
        aria-label={
          interactive
            ? `Radar of ${card.name} versus the cohort median on intelligence, coding, agentic, cost, and speed`
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
    card: ModelCard
    compare: ModelCard | null
    variant: 'preview' | 'interactive'
    onHoverAxis?: (axis: RadarAxisId | null) => void
  },
) {
  const { width, height, card, compare, variant, onHoverAxis } = options
  const interactive = variant === 'interactive'
  const tokens = readTokens(svgNode)
  const compact = !interactive || width < 520
  const margin = compact ? 36 : 56
  const radius = Math.max(Math.min(width, height) / 2 - margin, 40)
  const cx = width / 2
  const cy = height / 2 + (compact ? 4 : 0)
  const r = scaleLinear().domain([0, 1]).range([0, radius])
  const svg = select(svgNode)
  svg.selectAll('*').remove()
  svg.attr('viewBox', `0 0 ${width} ${height}`).attr('width', width).attr('height', height)
  svg.style('font-family', tokens.font)

  const plot = svg.append('g').attr('class', 'radar-plot')

  for (const tick of GRID_TICKS) {
    plot
      .append('path')
      .attr('class', 'radar-grid')
      .attr('d', polygonPath(RADAR_AXES.map((_, index) => polar(cx, cy, r(tick), angleAt(index)))))
      .attr('fill', 'none')
      .attr('stroke', tokens.border)
      .attr('stroke-width', tick === 0.5 ? 1.25 : 1)
  }

  RADAR_AXES.forEach((axis, index) => {
    const end = polar(cx, cy, radius, angleAt(index))
    plot
      .append('line')
      .attr('class', 'radar-spoke')
      .attr('data-axis', axis)
      .attr('x1', cx)
      .attr('y1', cy)
      .attr('x2', end[0])
      .attr('y2', end[1])
      .attr('stroke', tokens.border)
      .attr('stroke-width', 1)
  })

  plot
    .append('path')
    .attr('class', 'radar-median')
    .attr(
      'd',
      polygonPath(RADAR_AXES.map((_, index) => polar(cx, cy, r(0.5), angleAt(index)))),
    )
    .attr('fill', 'none')
    .attr('stroke', tokens.text)
    .attr('stroke-dasharray', '3 4')
    .attr('stroke-width', 1.25)

  if (compare && compare.key !== card.key) {
    drawProfile(plot, compare, cx, cy, r, tokens, 'compare')
  }
  drawProfile(plot, card, cx, cy, r, tokens, 'model')

  RADAR_AXES.forEach((axis, index) => {
    const measured = card.axes[axis].percentile !== null
    const labelPos = polar(cx, cy, radius + (compact ? 16 : 22), angleAt(index))
    const cosine = Math.cos(angleAt(index))
    plot
      .append('text')
      .attr('class', `radar-label${measured ? '' : ' is-missing'}`)
      .attr('data-axis', axis)
      .attr('x', labelPos[0])
      .attr('y', labelPos[1])
      .attr('text-anchor', Math.abs(cosine) < 0.2 ? 'middle' : cosine > 0 ? 'start' : 'end')
      .attr('dominant-baseline', 'central')
      .attr('fill', measured ? tokens.text : tokens.muted)
      .attr('font-size', compact ? 10 : 12)
      .attr('font-weight', 650)
      .text(compact ? RADAR_AXIS_META[axis].short : RADAR_AXIS_META[axis].label)
  })

  const points = radarPoints(card, cx, cy, r)
  if (interactive) {
    plot
      .selectAll('circle.radar-hit')
      .data(points)
      .join('circle')
      .attr('class', 'radar-hit')
      .attr('data-axis', (point) => point.axis)
      .attr('cx', (point) => point.hitX)
      .attr('cy', (point) => point.hitY)
      .attr('r', 14)
      .attr('fill', 'transparent')
      .style('cursor', 'pointer')
      .on('pointerenter', (_event, point) => onHoverAxis?.(point.axis))
      .on('pointerleave', () => onHoverAxis?.(null))
  }

  svg.on('pointerleave', () => onHoverAxis?.(null))
}

function drawProfile(
  plot: Selection<SVGGElement, unknown, null, undefined>,
  card: ModelCard,
  cx: number,
  cy: number,
  r: (value: number) => number,
  tokens: ChartTokens,
  kind: 'model' | 'compare',
) {
  const points = radarPoints(card, cx, cy, r)
  const measured = points.filter((point) => point.measured)
  const complete = isCompleteCard(card)
  if (complete) {
    plot
      .append('path')
      .attr('class', `radar-area radar-area--${kind}`)
      .attr('d', polygonPath(points.map((point) => [point.x, point.y])))
      .attr('fill', kind === 'model' ? tokens.primary : 'none')
      .attr('fill-opacity', kind === 'model' ? 0.22 : 0)
      .attr('stroke', kind === 'model' ? tokens.primaryStrong : tokens.muted)
      .attr('stroke-width', kind === 'model' ? 1.75 : 1.25)
      .attr('stroke-dasharray', kind === 'compare' ? '2 3' : null)
  } else {
    for (const run of measuredRuns(points)) {
      if (run.length < 2) continue
      plot
        .append('path')
        .attr('class', `radar-area radar-area--${kind} is-open`)
        .attr('d', openPath(run.map((point) => [point.x, point.y])))
        .attr('fill', 'none')
        .attr('stroke', kind === 'model' ? tokens.primaryStrong : tokens.muted)
        .attr('stroke-width', kind === 'model' ? 1.75 : 1.25)
        .attr('stroke-dasharray', kind === 'compare' ? '2 3' : '4 3')
    }
  }

  plot
    .selectAll(`circle.radar-vertex--${kind}`)
    .data(measured)
    .join('circle')
    .attr('class', `radar-vertex radar-vertex--${kind}`)
    .attr('data-axis', (point) => point.axis)
    .attr('cx', (point) => point.x)
    .attr('cy', (point) => point.y)
    .attr('r', kind === 'model' ? 3.5 : 2.5)
    .attr('fill', kind === 'model' ? tokens.primaryStrong : tokens.muted)
    .attr('stroke', tokens.surface)
    .attr('stroke-width', 1)
}

function radarPoints(
  card: ModelCard,
  cx: number,
  cy: number,
  r: (value: number) => number,
): RadarPoint[] {
  return RADAR_AXES.map((axis, index) => {
    const percentile = card.axes[axis].percentile
    const angle = angleAt(index)
    const vertexRadius = percentile !== null ? r(percentile) : 0
    const [x, y] = polar(cx, cy, vertexRadius, angle)
    const [hitX, hitY] = polar(
      cx,
      cy,
      percentile !== null ? vertexRadius : r(0.78),
      angle,
    )
    return {
      angle,
      axis,
      hitX,
      hitY,
      measured: percentile !== null,
      percentile,
      x,
      y,
    }
  })
}

function angleAt(index: number): number {
  return -Math.PI / 2 + (index / RADAR_AXES.length) * 2 * Math.PI
}

function polar(cx: number, cy: number, radius: number, angle: number): [number, number] {
  return [cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius]
}

function polygonPath(points: Array<[number, number]>): string {
  if (points.length === 0) return ''
  return `${points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0]},${point[1]}`).join('')}Z`
}

function openPath(points: Array<[number, number]>): string {
  return points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point[0]},${point[1]}`)
    .join('')
}

function measuredRuns(points: readonly RadarPoint[]): RadarPoint[][] {
  const runs: RadarPoint[][] = []
  let current: RadarPoint[] = []
  for (const point of points) {
    if (point.measured) {
      current.push(point)
      continue
    }
    if (current.length > 0) runs.push(current)
    current = []
  }
  if (current.length > 0) runs.push(current)
  return runs
}

function applyFocus(svg: SVGSVGElement, hoverAxis: RadarAxisId | null) {
  select(svg)
    .selectAll('.radar-spoke, .radar-label, .radar-vertex, .radar-hit')
    .classed('is-muted', function () {
      if (hoverAxis === null) return false
      return select(this).attr('data-axis') !== hoverAxis
    })
    .classed('is-active', function () {
      return hoverAxis !== null && select(this).attr('data-axis') === hoverAxis
    })
}

function readTokens(node: Element): ChartTokens {
  const styles = getComputedStyle(node)
  const rootStyles = getComputedStyle(document.documentElement)
  const token = (name: string) =>
    styles.getPropertyValue(name).trim() || rootStyles.getPropertyValue(name).trim()
  const primary = token('--color-primary') || '#176b68'
  return {
    border: token('--color-border') || '#ddd6cc',
    font: token('--font-sans') || 'DM Sans, sans-serif',
    muted: token('--color-text-muted') || '#6b736f',
    primary,
    primaryStrong: token('--color-primary-strong') || '#0c4f4d',
    surface: token('--color-surface') || '#fbf9f5',
    text: token('--color-text') || '#1a2422',
  }
}
