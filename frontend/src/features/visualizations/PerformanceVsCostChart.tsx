import { useLayoutEffect, useRef } from 'react'
import {
  axisBottom, axisLeft, brush, Delaunay, line, pointer,
  scaleLinear, scaleLog, select, type D3BrushEvent,
} from 'd3'

import { formatAxisCurrency, providerColor, type ScatterModel } from './scatter'
import { keysInScatterBounds, type CostScale } from './performanceComparison'

export interface PerformanceVsCostChartProps {
  model: ScatterModel
  variant: 'preview' | 'interactive'
  scoreLabel?: string
  costLabel?: string
  costScale?: CostScale
  xDomain?: [number, number]
  providers?: readonly string[]
  hoverKey?: string | null
  pinnedProvider?: string | null
  pinnedKeys?: readonly string[]
  brushedKeys?: readonly string[] | null
  brushMode?: boolean
  brushReset?: number
  /** `lower` shades the fast-or-cheap side on the left. `higher` shades the right. */
  xBetter?: 'lower' | 'higher'
  formatX?: (value: number) => string
  showScale?: boolean
  onHover?: (key: string | null) => void
  onSelect?: (key: string) => void
  onBrush?: (keys: string[] | null) => void
}

export function PerformanceVsCostChart(props: PerformanceVsCostChartProps) {
  const { model, variant, scoreLabel = 'Intelligence index',
    costLabel = 'Cost per task, USD', costScale = 'log', xDomain,
    providers, brushMode = false, brushReset = 0, xBetter = 'lower',
    formatX = formatAxisCurrency, showScale = true } = props
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)
  const propsRef = useRef(props)
  useLayoutEffect(() => { propsRef.current = props })

  useLayoutEffect(() => {
    const wrapper = wrapRef.current
    const svgNode = svgRef.current
    if (!wrapper || !svgNode) return
    const render = () => {
      const width = wrapper.clientWidth
      const height = wrapper.clientHeight
      if (width < 100 || height < 100) return
      const interactive = variant === 'interactive'
      const styles = getComputedStyle(document.documentElement)
      const color = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
      const text = color('--color-text', '#1a2422')
      const muted = color('--color-text-muted', '#6b736f')
      const border = color('--color-border', '#ddd6cc')
      const surface = color('--color-surface', '#fbf9f5')
      const primary = color('--color-primary-strong', '#176b68')
      const margin = { top: 26, right: 24, bottom: 54, left: interactive ? 70 : 48 }
      const w = width - margin.left - margin.right
      const h = height - margin.top - margin.bottom
      const costs = model.points.map((point) => point.cost)
      const minCost = costs.length ? Math.min(...costs) : 1
      const maxCost = costs.length ? Math.max(...costs) : 1
      const domain: [number, number] = xDomain ?? (costScale === 'log'
        ? [minCost * 0.8, maxCost === minCost ? maxCost * 1.5 : maxCost * 1.2]
        : [0, Math.max(maxCost * 1.12, 1)])
      const x = (costScale === 'log' ? scaleLog() : scaleLinear()).domain(domain).range([0, w])
      const scores = model.points.map((point) => point.intelligence)
      const minScore = scores.length ? Math.min(...scores) : 0
      const maxScore = scores.length ? Math.max(...scores) : 1
      const span = maxScore - minScore || Math.max(Math.abs(maxScore) * 0.15, 0.01)
      // Agent scores can be negative; all Y domains retain their actual range.
      const y = scaleLinear().domain([minScore - span * 0.12, maxScore + span * 0.15]).range([h, 0])
      const providerKeys = providers ?? model.points.map((point) => point.providerKey)
      const svg = select(svgNode)
      svg.selectAll('*').remove()
      svg.attr('viewBox', `0 0 ${width} ${height}`)
      const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
      if (model.points.length) {
        const medianX = x(model.medianCost)
        const quadrant = plot.append('rect').attr('class', 'pareto-quadrant')
          .attr('y', 0)
          .attr('height', Math.max(0, y(model.medianIntelligence)))
          .attr('fill', primary).attr('fill-opacity', 0.08)
        if (xBetter === 'higher') {
          quadrant.attr('x', medianX).attr('width', Math.max(0, w - medianX))
        } else {
          quadrant.attr('x', 0).attr('width', Math.max(0, medianX))
        }
      }
      const xTicks = costScale === 'log' ? x.ticks(7).filter((value) => {
        const significant = value / 10 ** Math.floor(Math.log10(value))
        return [1, 2, 5].some((tick) => Math.abs(significant - tick) < 0.001)
      }) : x.ticks(width < 500 ? 4 : 6)
      const yTicks = y.ticks(5)
      plot.append('g').selectAll('line').data(yTicks).join('line')
        .attr('x2', w).attr('y1', y).attr('y2', y).attr('stroke', border)
      const xAxis = plot.append('g').attr('transform', `translate(0,${h})`)
        .call(axisBottom(x).tickValues(xTicks).tickFormat((value) => formatX(Number(value))).tickSizeOuter(0))
      const yAxis = plot.append('g').call(axisLeft(y).tickValues(yTicks).tickFormat((value) =>
        new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(Number(value)),
      ).tickSizeOuter(0))
      for (const axis of [xAxis, yAxis]) {
        axis.selectAll('line,path').attr('stroke', border)
        axis.selectAll('text').attr('fill', muted).attr('font-size', 10)
      }
      plot.append('text').attr('class', 'pareto-axis-title').attr('x', w / 2).attr('y', h + 40)
        .attr('text-anchor', 'middle').attr('fill', muted).attr('font-size', 10)
        .text(showScale ? `${costLabel} (${costScale === 'log' ? 'log' : 'linear'})` : costLabel)
      if (interactive) {
        plot.append('text').attr('transform', 'rotate(-90)').attr('x', -h / 2).attr('y', -54)
          .attr('text-anchor', 'middle').attr('fill', muted).attr('font-size', 10).text(scoreLabel)
      }
      const path = line<(typeof model.points)[number]>().x((point) => x(point.cost)).y((point) => y(point.intelligence))
      plot.append('path').attr('class', 'pareto-front-line').attr('d', path(model.pareto) ?? '')
        .attr('fill', 'none').attr('stroke', text).attr('stroke-width', 1.5).attr('stroke-dasharray', '3 4')
      plot.append('line').attr('class', 'pareto-hair-x').attr('stroke', muted).attr('stroke-dasharray', '2 3').attr('opacity', 0)
      plot.append('line').attr('class', 'pareto-hair-y').attr('stroke', muted).attr('stroke-dasharray', '2 3').attr('opacity', 0)
      const dots = plot.append('g').attr('class', 'pareto-points').selectAll('circle').data(model.points).join('circle')
        .attr('class', 'pareto-dot').attr('data-key', (point) => point.key)
        .attr('cx', (point) => x(point.cost)).attr('cy', (point) => y(point.intelligence))
        .attr('r', (point) => point.onPareto ? 6.5 : 4.5)
        .attr('fill', (point) => interactive ? providerColor(point.providerKey, providerKeys) : primary)
        .attr('stroke', (point) => point.onPareto ? text : surface).attr('stroke-width', 1.5)
      dots.append('title').text((point) => `${point.name}: ${point.intelligence}; ${formatX(point.cost)}`)
      const focusLabels = plot.append('g').attr('class', 'pareto-focus-labels')
      const nearest = Delaunay.from(model.points, (point) => x(point.cost), (point) => y(point.intelligence))
      const nearestKey = (event: MouseEvent) => {
        if (!model.points.length) return null
        const [mx, my] = pointer(event, plot.node())
        const point = model.points[nearest.find(mx, my)]
        return Math.hypot(x(point.cost) - mx, y(point.intelligence) - my) <= 25 ? point.key : null
      }
      if (interactive && brushMode) {
        const behavior = brush<unknown>().extent([[0, 0], [w, h]])
          .on('start', (event: D3BrushEvent<unknown>) => {
            if (event.sourceEvent) propsRef.current.onHover?.(null)
          })
          .on('brush end', (event: D3BrushEvent<unknown>) => {
            if (!event.sourceEvent) return
            if (!event.selection) { propsRef.current.onBrush?.(null); return }
            const [[x0, y0], [x1, y1]] = event.selection as [[number, number], [number, number]]
            propsRef.current.onBrush?.(keysInScatterBounds(model, {
              x: [x.invert(x0), x.invert(x1)], y: [y.invert(y1), y.invert(y0)],
            }))
          })
        plot.append('g').attr('class', 'performance-brush').call(behavior)
      } else if (interactive) {
        plot.append('rect').attr('class', 'pareto-hitbox').attr('width', w).attr('height', h)
          .attr('fill', 'transparent').style('touch-action', 'pan-y')
          .on('pointermove', (event: MouseEvent) => propsRef.current.onHover?.(nearestKey(event)))
          .on('pointerleave', () => propsRef.current.onHover?.(null))
          .on('click', (event: MouseEvent) => { const key = nearestKey(event); if (key) propsRef.current.onSelect?.(key) })
      }
      const applyFocus = () => {
        const { hoverKey, pinnedKeys = [], brushedKeys = null, pinnedProvider = null } = propsRef.current
        const selected = new Set(pinnedKeys)
        const brushed = brushedKeys === null ? null : new Set(brushedKeys)
        dots.each(function (point) {
          const node = select(this)
          const active = point.key === hoverKey || selected.has(point.key)
          const matched = brushed !== null && brushed.has(point.key)
          const mutedPoint = !active && !matched && ((hoverKey != null) ||
            brushed !== null ||
            (pinnedProvider !== null && point.providerKey !== pinnedProvider) ||
            selected.size > 0)
          node.classed('is-muted', mutedPoint).classed('is-active', active)
            .classed('is-pinned', selected.has(point.key))
            .attr('r', active ? 8 : point.onPareto ? 6.5 : 4.5)
            .attr('stroke-width', selected.has(point.key) ? 3 : 1.5)
          if (active) node.raise()
        })
        const hovered = model.points.find((point) => point.key === hoverKey)
        const labels = model.points.filter((point) => point.key === hoverKey)
        focusLabels.selectAll('text').data(labels).join('text')
          .attr('x', (point) => x(point.cost) + (x(point.cost) > w * 0.6 ? -12 : 12))
          .attr('y', (point) => Math.max(12, y(point.intelligence) - 13))
          .attr('text-anchor', (point) => x(point.cost) > w * 0.6 ? 'end' : 'start')
          .attr('fill', text).attr('font-size', 11).attr('font-weight', 650)
          .attr('paint-order', 'stroke').attr('stroke', surface).attr('stroke-width', 4)
          .style('pointer-events', 'none').text((point) => point.name)
        plot.select('.pareto-hair-x').attr('opacity', hovered ? 0.8 : 0)
          .attr('x1', 0).attr('x2', hovered ? x(hovered.cost) : 0)
          .attr('y1', hovered ? y(hovered.intelligence) : 0).attr('y2', hovered ? y(hovered.intelligence) : 0)
        plot.select('.pareto-hair-y').attr('opacity', hovered ? 0.8 : 0)
          .attr('x1', hovered ? x(hovered.cost) : 0).attr('x2', hovered ? x(hovered.cost) : 0)
          .attr('y1', h).attr('y2', hovered ? y(hovered.intelligence) : 0)
      }
      svg.datum({ applyFocus })
      applyFocus()
    }
    render()
    const observer = new ResizeObserver(render)
    observer.observe(wrapper)
    const themes = new MutationObserver(render)
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { observer.disconnect(); themes.disconnect() }
  }, [model, variant, scoreLabel, costLabel, costScale, xDomain, providers, brushMode, brushReset, xBetter, formatX, showScale])

  useLayoutEffect(() => {
    const svg = svgRef.current
    if (svg) (select(svg).datum() as { applyFocus: () => void } | undefined)?.applyFocus()
  }, [props.hoverKey, props.pinnedKeys, props.brushedKeys, props.pinnedProvider])

  return (
    <div className={`pareto-chart pareto-chart--${variant}`} ref={wrapRef}>
      <svg ref={svgRef} role={variant === 'interactive' ? 'img' : undefined}
        aria-hidden={variant === 'preview' ? true : undefined}
        aria-label={variant === 'interactive' ? `${scoreLabel} versus ${costLabel}` : undefined} />
    </div>
  )
}
