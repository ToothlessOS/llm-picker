import { useLayoutEffect, useRef } from 'react'
import {
  axisLeft, axisRight, brushY, line, scaleLinear, scaleLog, scalePoint, select,
  type D3BrushEvent, type ScaleLinear, type ScaleLog,
} from 'd3'

import { formatAxisCurrency } from './scatter'
import {
  COMPARE_STROKES, PARALLEL_AXES, PARALLEL_AXIS_LABELS, parallelValue,
  type CostScale, type ParallelAxis, type ParallelRecord,
} from './performanceComparison'

export interface ParallelCoordinatesChartProps {
  records: readonly ParallelRecord[]
  /** First axis plus the three scores. Defaults to cost, intelligence, coding, agent. */
  axes?: readonly ParallelAxis[]
  costScale: CostScale
  costDomain: readonly [number, number]
  costLabel: string
  /** Smaller values sit at the top. True for cost and time-to-first-token. */
  lowerIsBetter?: boolean
  formatLead?: (value: number) => string
  leadTitle?: string
  leadHint?: string
  hoverKey?: string | null
  pinnedKeys?: readonly string[]
  brushedKeys?: readonly string[] | null
  brushReset?: number
  onHover?: (key: string | null) => void
  onSelect?: (key: string) => void
  onAxisBrush?: (axis: ParallelAxis, range: readonly [number, number] | null) => void
}

function scoreScale(values: readonly number[], height: number) {
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const span = max - min || Math.max(Math.abs(max) * 0.2, 1)
  return scaleLinear().domain([min - span * 0.08, max + span * 0.08]).range([height, 0])
}

export function ParallelCoordinatesChart(props: ParallelCoordinatesChartProps) {
  const {
    records, axes = PARALLEL_AXES, costScale, costDomain, costLabel,
    lowerIsBetter = true, formatLead, leadTitle, leadHint, brushReset = 0,
  } = props
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
      if (width < 160 || height < 140) return
      const styles = getComputedStyle(document.documentElement)
      const color = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
      const text = color('--color-text', '#1a2422')
      const muted = color('--color-text-muted', '#6b736f')
      const border = color('--color-border', '#ddd6cc')
      const margin = { top: 28, right: 46, bottom: 46, left: 58 }
      const w = width - margin.left - margin.right
      const h = height - margin.top - margin.bottom
      const x = scalePoint<ParallelAxis>().domain([...axes]).range([0, w]).padding(0)
      const lead = axes[0]
      const y = new Map<ParallelAxis, ScaleLinear<number, number> | ScaleLog<number, number>>()
      for (const axis of axes) {
        if (axis === lead) {
          y.set(axis, (costScale === 'log' ? scaleLog() : scaleLinear())
            .domain([...costDomain])
            .range(lowerIsBetter ? [0, h] : [h, 0]))
        } else {
          y.set(axis, scoreScale(records.flatMap((record) => {
            const value = parallelValue(record, axis)
            return value === null ? [] : [value]
          }), h))
        }
      }
      const svg = select(svgNode)
      svg.selectAll('*').remove()
      svg.attr('viewBox', `0 0 ${width} ${height}`)
      const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
      const lineFor = (record: ParallelRecord) => line<ParallelAxis>()
        .defined((axis) => parallelValue(record, axis) !== null)
        .x((axis) => x(axis) ?? 0)
        .y((axis) => {
          const scale = y.get(axis)
          return scale ? scale(parallelValue(record, axis) ?? 0) : 0
        })(axes) ?? ''
      const lines = plot.append('g').attr('class', 'parallel-lines').selectAll('path')
        .data(records).join('path')
        .attr('class', 'parallel-line')
        .attr('data-key', (record) => record.key)
        .attr('d', (record) => lineFor(record))
        .attr('fill', 'none')
        .attr('stroke', muted)
        .attr('stroke-width', 1.25)
        .attr('stroke-linejoin', 'round')
        .attr('stroke-linecap', 'round')
      lines.append('title').text((record) => record.name)
      const hits = plot.append('g').attr('class', 'parallel-hits').selectAll('path')
        .data(records).join('path')
        .attr('d', (record) => lineFor(record))
        .attr('fill', 'none')
        .attr('stroke', 'transparent')
        .attr('stroke-width', 10)
        .style('cursor', 'pointer')
        .on('pointerenter', (_event, record) => propsRef.current.onHover?.(record.key))
        .on('pointerleave', () => propsRef.current.onHover?.(null))
        .on('click', (_event, record) => propsRef.current.onSelect?.(record.key))
      void hits

      axes.forEach((axis, index) => {
        const axisX = x(axis) ?? 0
        const group = plot.append('g').attr('transform', `translate(${axisX},0)`)
        const scale = y.get(axis) ?? scaleLinear()
        const ticks = axis === lead && costScale === 'log'
          ? scale.ticks(5).filter((value) => {
            const significant = value / 10 ** Math.floor(Math.log10(value))
            return [1, 2, 5].some((tick) => Math.abs(significant - tick) < 0.001)
          })
          : scale.ticks(4)
        const axisMark = (index === axes.length - 1 ? axisRight(scale) : axisLeft(scale))
          .tickValues(ticks)
          .tickFormat((value) => axis === lead
            ? (formatLead ? formatLead(Number(value)) : formatAxisCurrency(Number(value)))
            : new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(Number(value)))
          .tickSizeOuter(0)
        const drawn = group.append('g').call(axisMark)
        drawn.selectAll('line,path').attr('stroke', border)
        drawn.selectAll('text').attr('fill', muted).attr('font-size', 10)
        group.append('text').attr('y', h + 28).attr('text-anchor', 'middle')
          .attr('fill', text).attr('font-size', 12).attr('font-weight', 650)
          .text(axis === lead && leadTitle ? leadTitle : PARALLEL_AXIS_LABELS[axis])
        group.append('text').attr('y', -12).attr('text-anchor', 'middle')
          .attr('fill', muted).attr('font-size', 9)
          .text(axis === lead ? (leadHint ?? 'cheaper ↑') : 'higher ↑')
        const behavior = brushY().extent([[-14, 0], [14, h]])
          .on('end', (event: D3BrushEvent<unknown>) => {
            if (!event.sourceEvent) return
            if (!event.selection) { propsRef.current.onAxisBrush?.(axis, null); return }
            const [y0, y1] = event.selection as [number, number]
            const low = Number(scale.invert(y0))
            const high = Number(scale.invert(y1))
            propsRef.current.onAxisBrush?.(axis, [Math.min(low, high), Math.max(low, high)])
          })
        group.append('g').attr('class', 'performance-brush parallel-brush').call(behavior)
      })

      const applyFocus = () => {
        const { hoverKey = null, pinnedKeys = [], brushedKeys = null } = propsRef.current
        const pinned = new Map(pinnedKeys.map((key, index) => [key, index]))
        const brushed = brushedKeys === null ? null : new Set(brushedKeys)
        lines.each(function (record) {
          const node = select(this)
          const pinIndex = pinned.get(record.key)
          const active = record.key === hoverKey || pinIndex !== undefined
          const matched = brushed !== null && brushed.has(record.key)
          const faded = !active && !matched && (hoverKey !== null || brushed !== null)
          const stroke = pinIndex !== undefined ? COMPARE_STROKES[pinIndex] ?? text
            : record.key === hoverKey ? text
              : matched ? text : muted
          node.classed('is-muted', faded).classed('is-active', active)
            .attr('stroke', stroke)
            .attr('stroke-opacity', faded ? 0.12 : active ? 1 : matched ? 0.72 : 0.28)
            .attr('stroke-width', active ? 2.6 : matched ? 1.6 : 1.15)
          if (active || matched) node.raise()
        })
        hits.each(function (record) {
          if (record.key === hoverKey || pinned.has(record.key)) select(this).raise()
        })
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
  }, [records, axes, costScale, costDomain, costLabel, lowerIsBetter, formatLead, leadTitle, leadHint, brushReset])

  useLayoutEffect(() => {
    const svg = svgRef.current
    if (svg) (select(svg).datum() as { applyFocus: () => void } | undefined)?.applyFocus()
  }, [props.hoverKey, props.pinnedKeys, props.brushedKeys])

  return (
    <div className="pareto-chart pareto-chart--interactive" ref={wrapRef}>
      <svg ref={svgRef} role="img" aria-label={axes[0] === 'speed'
        ? `Parallel coordinates of ${costLabel}, intelligence, coding, and agent score. A higher position is faster.`
        : `Parallel coordinates of ${costLabel}, intelligence, coding, and agent score. Cost points upward as it gets cheaper.`} />
    </div>
  )
}
