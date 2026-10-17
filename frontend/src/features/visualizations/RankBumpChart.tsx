import { useLayoutEffect, useRef } from 'react'
import { axisLeft, line, scaleLinear, scalePoint, select } from 'd3'

import {
  COMPARE_STROKES, PERFORMANCE_METRICS, PERFORMANCE_SHORT_LABELS,
  type PerformanceMetric,
} from './performanceComparison'

export interface RankSeries {
  key: string
  name: string
  ranks: Partial<Record<PerformanceMetric, number>>
}

export function RankBumpChart({ series, cohortSize }: { series: readonly RankSeries[]; cohortSize: number }) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  useLayoutEffect(() => {
    const wrapper = wrapRef.current
    const svgNode = svgRef.current
    if (!wrapper || !svgNode) return
    const render = () => {
      const width = wrapper.clientWidth
      const height = wrapper.clientHeight
      if (width < 160 || height < 120) return
      const styles = getComputedStyle(document.documentElement)
      const color = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback
      const text = color('--color-text', '#1a2422')
      const muted = color('--color-text-muted', '#6b736f')
      const border = color('--color-border', '#ddd6cc')
      const surface = color('--color-surface', '#fbf9f5')
      const margin = { top: 18, right: 120, bottom: 36, left: 46 }
      const w = width - margin.left - margin.right
      const h = height - margin.top - margin.bottom
      const maxRank = Math.max(cohortSize, 1, ...series.flatMap((item) => Object.values(item.ranks).filter((rank): rank is number => rank !== undefined)))
      const x = scalePoint<PerformanceMetric>().domain([...PERFORMANCE_METRICS]).range([0, w]).padding(0.2)
      const y = scaleLinear().domain([1, maxRank]).range([0, h])
      const svg = select(svgNode)
      svg.selectAll('*').remove()
      svg.attr('viewBox', `0 0 ${width} ${height}`)
      const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)
      const yAxis = plot.append('g').call(axisLeft(y).ticks(Math.min(maxRank, 5)).tickFormat((value) => `${value}`).tickSizeOuter(0))
      yAxis.selectAll('line,path').attr('stroke', border)
      yAxis.selectAll('text').attr('fill', muted).attr('font-size', 10)
      plot.append('text').attr('transform', 'rotate(-90)').attr('x', -h / 2).attr('y', -34)
        .attr('text-anchor', 'middle').attr('fill', muted).attr('font-size', 10).text('Rank')
      PERFORMANCE_METRICS.forEach((metric) => {
        const axisX = x(metric) ?? 0
        plot.append('line').attr('x1', axisX).attr('x2', axisX).attr('y1', 0).attr('y2', h)
          .attr('stroke', border)
        plot.append('text').attr('x', axisX).attr('y', h + 24).attr('text-anchor', 'middle')
          .attr('fill', text).attr('font-size', 12).attr('font-weight', 650)
          .text(PERFORMANCE_SHORT_LABELS[metric])
      })
      series.forEach((item, index) => {
        const stroke = COMPARE_STROKES[index] ?? text
        const points = PERFORMANCE_METRICS.flatMap((metric) => {
          const rank = item.ranks[metric]
          return rank === undefined ? [] : [{ metric, rank }]
        })
        plot.append('path').attr('fill', 'none').attr('stroke', stroke).attr('stroke-width', 2.2)
          .attr('d', line<(typeof points)[number]>().x((point) => x(point.metric) ?? 0).y((point) => y(point.rank))(points) ?? '')
        plot.selectAll(null).data(points).join('circle')
          .attr('cx', (point) => x(point.metric) ?? 0).attr('cy', (point) => y(point.rank)).attr('r', 4.5)
          .attr('fill', stroke).attr('stroke', surface).attr('stroke-width', 1.5)
          .append('title').text((point) => `${item.name} ${PERFORMANCE_SHORT_LABELS[point.metric]} rank ${point.rank}`)
        const last = points.at(-1)
        if (last) {
          plot.append('text').attr('x', (x(last.metric) ?? 0) + 12).attr('y', y(last.rank) + 4)
            .attr('fill', stroke).attr('font-size', 11).attr('font-weight', 650)
            .text(item.name)
        }
      })
    }
    render()
    const observer = new ResizeObserver(render)
    observer.observe(wrapper)
    const themes = new MutationObserver(render)
    themes.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { observer.disconnect(); themes.disconnect() }
  }, [series, cohortSize])

  return (
    <div className="pareto-chart pareto-chart--interactive" ref={wrapRef}>
      <svg ref={svgRef} role="img" aria-label="Rank comparison across intelligence, coding, and agent score. Rank 1 is at the top." />
    </div>
  )
}
