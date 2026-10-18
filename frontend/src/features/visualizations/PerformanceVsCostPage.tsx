import { useCallback, useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight, MousePointer2, Pin, RotateCcw, SquareDashedMousePointer, X } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import type { OverviewRow } from '../../api'
import { formatCurrency, formatDateTime } from '../../app/format'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { ParallelCoordinatesChart } from './ParallelCoordinatesChart'
import { PerformanceVsCostChart } from './PerformanceVsCostChart'
import { RankBumpChart } from './RankBumpChart'
import { providerColor, providerLabel } from './scatter'
import {
  buildParallelRecords, buildPerformanceComparison, combineBrushes, COMPARE_STROKES,
  COST_LABELS, costValue, formatPerformance, keysMatchingAxisBrushes, metricRanks,
  PARALLEL_AXIS_LABELS, PARALLEL_AXES, PERFORMANCE_LABELS, PERFORMANCE_METRICS, SPEED_PARALLEL_AXES,
  performanceValue, toggleComparedModel,
  type AxisBrushes, type CostMetric, type CostScale, type ParallelAxis, type PerformanceMetric,
} from './performanceComparison'
import {
  buildSpeedComparison, buildSpeedParallelRecords, formatSpeed, SPEED_LABELS, SPEED_METRICS, speedValue,
  type SpeedMetric,
} from './speedComparison'
import { useOverviewPerformance } from './useOverviewScatter'

export function PerformanceVsCostPage() {
  const location = useLocation()
  const query = useOverviewPerformance()
  const [explorer, setExplorer] = useState<'cost' | 'speed'>('cost')
  const [speedMetric, setSpeedMetric] = useState<SpeedMetric>('output')
  const [costMetric, setCostMetric] = useState<CostMetric>('task')
  const [costScale, setCostScale] = useState<CostScale>('log')
  const [provider, setProvider] = useState<string | null>(null)
  const [layout, setLayout] = useState<'focus' | 'compare'>('focus')
  const [metric, setMetric] = useState<PerformanceMetric>('intelligence')
  const [views, setViews] = useState<PerformanceMetric[]>([...PERFORMANCE_METRICS])
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [inspectedKey, setInspectedKey] = useState<string | null>(null)
  const [pinnedKeys, setPinnedKeys] = useState<string[]>([])
  const [scatterBrushKeys, setScatterBrushKeys] = useState<string[] | null>(null)
  const [axisBrushes, setAxisBrushes] = useState<AxisBrushes>({})
  const [brushSource, setBrushSource] = useState<PerformanceMetric | null>(null)
  const [brushMode, setBrushMode] = useState(false)
  const [scatterBrushReset, setScatterBrushReset] = useState(0)
  const [parallelBrushReset, setParallelBrushReset] = useState(0)
  const [viewBrushResets, setViewBrushResets] = useState({ intelligence: 0, coding: 0, agent: 0 })
  const [message, setMessage] = useState('')
  const rows = query.data?.results
  const comparison = useMemo(() =>
    buildPerformanceComparison(rows ?? [], costMetric, costScale, provider),
  [rows, costMetric, costScale, provider])
  const speedComparison = useMemo(() =>
    buildSpeedComparison(rows ?? [], metric, speedMetric, provider),
  [rows, metric, speedMetric, provider])
  const formatSpeedAxis = useCallback((value: number) =>
    new Intl.NumberFormat(undefined, { maximumFractionDigits: speedMetric === 'output' ? 0 : 1 }).format(value),
  [speedMetric])
  const providers = useMemo(() => [...new Set((rows ?? []).map((row) =>
    row.model.organization ?? 'unknown',
  ))].sort(), [rows])
  const inspected = rows?.find((row) => row.model.key === (hoverKey ?? inspectedKey ?? pinnedKeys.at(-1)))
  const pinnedRows = pinnedKeys.map((key) => rows?.find((row) => row.model.key === key))
    .filter((row): row is OverviewRow => row !== undefined)
  const records = useMemo(() => buildParallelRecords(comparison.rows, costMetric, costScale),
    [comparison.rows, costMetric, costScale])
  const speedRecords = useMemo(() => buildSpeedParallelRecords(comparison.rows, speedMetric),
    [comparison.rows, speedMetric])
  const parallelKeys = useMemo(() => keysMatchingAxisBrushes(
    explorer === 'speed' ? speedRecords : records, axisBrushes,
  ), [explorer, speedRecords, records, axisBrushes])
  const brushedKeys = useMemo(() => combineBrushes(parallelKeys, scatterBrushKeys), [parallelKeys, scatterBrushKeys])
  const ranks = useMemo(() => Object.fromEntries(PERFORMANCE_METRICS.map((item) =>
    [item, metricRanks(comparison.rows, item)])) as Record<PerformanceMetric, Map<string, number>>, [comparison.rows])
  const visibleKeys = useMemo(() => new Set(PERFORMANCE_METRICS.flatMap((item) =>
    comparison.models[item].points.map((point) => point.key),
  )), [comparison])
  const activeAxes = (explorer === 'speed' ? SPEED_PARALLEL_AXES : PARALLEL_AXES)
    .filter((axis) => axisBrushes[axis] !== undefined)
  const listedRows = comparison.rows.filter((row) => {
    const plotted = explorer === 'speed'
      ? speedComparison.points.some((point) => point.key === row.model.key)
      : visibleKeys.has(row.model.key)
    if (brushedKeys === null) return plotted
    return plotted && brushedKeys.includes(row.model.key)
  })
  const activeMetrics = layout === 'focus' ? [metric] : PERFORMANCE_METRICS.filter((item) => views.includes(item))
  const rankSeries = pinnedRows.map((row) => ({
    key: row.model.key,
    name: row.model.name,
    ranks: Object.fromEntries(PERFORMANCE_METRICS.flatMap((item) => {
      const rank = ranks[item].get(row.model.key)
      return rank === undefined ? [] : [[item, rank]]
    })) as Partial<Record<PerformanceMetric, number>>,
  }))

  const clearBrush = () => {
    setScatterBrushKeys(null)
    setAxisBrushes({})
    setBrushSource(null)
    setScatterBrushReset((value) => value + 1)
    setParallelBrushReset((value) => value + 1)
  }
  const brushAxis = (axis: ParallelAxis, range: readonly [number, number] | null) => {
    setScatterBrushKeys(null)
    setBrushSource(null)
    setScatterBrushReset((value) => value + 1)
    setAxisBrushes((current) => {
      const next = { ...current }
      if (range === null) delete next[axis]
      else next[axis] = range
      return next
    })
  }
  const togglePin = (key: string) => {
    setInspectedKey(key)
    setMessage(pinnedKeys.length === 3 && !pinnedKeys.includes(key)
      ? 'Comparison is full. Unpin a model to add another.' : '')
    setPinnedKeys((current) => toggleComparedModel(current, key))
  }
  const resetSelection = () => {
    clearBrush()
    setPinnedKeys([])
    setHoverKey(null)
    setInspectedKey(null)
    setMessage('')
  }
  const toggleView = (metric: PerformanceMetric) => {
    setViews((current) => current.includes(metric)
      ? current.filter((item) => item !== metric) : [...current, metric])
    if (brushSource === metric) clearBrush()
    setHoverKey(null)
  }

  return (
    <main className="page performance-page">
      <Link className="back-link" to={{ pathname: '/', search: location.search, hash: 'visualizations' }}>
        <ArrowLeft aria-hidden="true" size={16} />All charts
      </Link>
      <PageHeader title="Performance explorer" count={rows?.length}
        isFetching={query.isFetching && !query.isPending}
        description={explorer === 'cost'
          ? 'Compare capability with cost, then test several conditions at once.'
          : 'Compare capability with speed. Faster output and a shorter wait for the first token are separate questions.'} />
      {query.isPending ? <LoadingState label="Loading performance versus cost" rows={5} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
      {rows?.length === 0 ? <EmptyState message="No matched models are available." /> : null}

      {rows && rows.length > 0 ? <>
        <div className="performance-explorer" role="tablist" aria-label="Performance explorer views">
          <button type="button" role="tab" aria-selected={explorer === 'cost'}
            onClick={() => { setExplorer('cost'); clearBrush(); setHoverKey(null) }}>Performance vs. cost</button>
          <button type="button" role="tab" aria-selected={explorer === 'speed'}
            onClick={() => { setExplorer('speed'); clearBrush(); setHoverKey(null) }}>Performance vs. speed</button>
        </div>
        <section className="performance-controls" aria-label="Comparison controls">
          {explorer === 'cost' ? <label className="performance-control performance-control--cost">
            <span>Cost reference</span>
            <select value={costMetric} onChange={(event) => { setCostMetric(event.target.value as CostMetric); clearBrush() }}>
              <option value="task">AA cost / Intelligence Index task</option>
              <option value="input">Input price / million tokens</option>
              <option value="output">Output price / million tokens</option>
            </select>
          </label> : <label className="performance-control performance-control--cost">
            <span>Speed measure</span>
            <select aria-label="Speed measure" value={speedMetric} onChange={(event) => {
              setSpeedMetric(event.target.value as SpeedMetric); clearBrush(); setHoverKey(null)
            }}>
              {SPEED_METRICS.map((item) => <option key={item} value={item}>{SPEED_LABELS[item]}</option>)}
            </select>
          </label>}
          {explorer === 'cost' ? <fieldset className="performance-control">
            <legend>Cost scale</legend>
            <div className="performance-segmented">
              {(['log', 'linear'] as const).map((scale) => <label key={scale}>
                <input type="radio" name="cost-scale" value={scale} checked={costScale === scale}
                  onChange={() => { setCostScale(scale); clearBrush() }} />
                <span>{scale === 'log' ? 'Log' : 'Linear'}</span>
              </label>)}
            </div>
          </fieldset> : null}
          {explorer === 'speed' || layout === 'focus' ? <label className="performance-control">
            <span>Performance</span>
            <select aria-label="Performance" value={metric} onChange={(event) => {
              setMetric(event.target.value as PerformanceMetric); clearBrush(); setHoverKey(null)
            }}>
              {PERFORMANCE_METRICS.map((item) => <option key={item} value={item}>{PERFORMANCE_LABELS[item]}</option>)}
            </select>
          </label> : null}
          {explorer === 'cost' ? <fieldset className="performance-control">
            <legend>Layout</legend>
            <div className="performance-segmented">
              {([['focus', 'Single view'], ['compare', 'Compare views']] as const).map(([value, label]) => <label key={value}>
                <input type="radio" name="performance-layout" value={value} checked={layout === value}
                  onChange={() => { setLayout(value); clearBrush(); setHoverKey(null) }} />
                <span>{label}</span>
              </label>)}
            </div>
          </fieldset> : null}
          <label className="performance-control">
            <span>Provider</span>
            <select value={provider ?? ''} onChange={(event) => {
              setProvider(event.target.value || null); clearBrush(); setHoverKey(null)
            }}>
              <option value="">All providers</option>
              {providers.map((key) => <option key={key} value={key}>{providerLabel(key)}</option>)}
            </select>
          </label>
          <div className="performance-tools" role="group" aria-label="Selection tool">
            <button type="button" title="Inspect and pin models" aria-label="Inspect and pin models"
              aria-pressed={!brushMode} onClick={() => setBrushMode(false)}><MousePointer2 size={18} /></button>
            <button type="button" title="Brush a group of models" aria-label="Brush a group of models"
              aria-pressed={brushMode} onClick={() => { setBrushMode(true); setHoverKey(null) }}><SquareDashedMousePointer size={18} /></button>
            <button type="button" title="Clear selection" aria-label="Clear selection"
              disabled={!pinnedKeys.length && brushedKeys === null && !inspectedKey}
              onClick={resetSelection}><RotateCcw size={18} /></button>
          </div>
        </section>
        <div className="performance-view-bar">
          {explorer === 'cost' && layout === 'compare' ? <fieldset className="performance-views"><legend>Views</legend>
            {PERFORMANCE_METRICS.map((item) => <label key={item}>
              <input type="checkbox" checked={views.includes(item)} onChange={() => toggleView(item)} />
              {PERFORMANCE_LABELS[item]}
            </label>)}
          </fieldset> : <p className="performance-cost-note performance-cost-note--inline">{explorer === 'cost'
            ? 'Drag a band on a parallel axis to keep models inside that range. Bands on several axes are combined with AND.'
            : 'Output speed is better farther right. Time to first token is better farther left. Drag a band on a parallel axis to keep models inside that range.'}</p>}
          <p className="performance-status" role="status">
            {message || (brushedKeys !== null
              ? `${brushedKeys.length} models match ${activeAxes.length ? activeAxes.map((axis) => PARALLEL_AXIS_LABELS[axis]).join(' and ') : 'the scatter brush'}`
              : explorer === 'speed'
                ? `${speedComparison.points.length} models with measured ${speedMetric === 'output' ? 'output speed' : 'latency'}`
                : `${visibleKeys.size} models with measured cost`)}
            <span>{pinnedKeys.length} / 3 pinned</span>
            {brushedKeys !== null ? <button type="button" title="Clear brush" aria-label="Clear brush" onClick={clearBrush}><X size={14} /></button> : null}
          </p>
        </div>
        {explorer === 'cost' ? <p className="performance-cost-note">{costMetric === 'task'
          ? 'Cost is the AA Intelligence Index workload estimate, not a measured cost for Coding or LMArena Agent tasks.'
          : 'Token prices are AA list prices; they do not include model-specific token usage.'}
          {costScale === 'log' ? ' Zero and missing costs are omitted on the log axis.' : ' Missing costs are omitted; measured zero prices are included.'}</p>
          : <p className="performance-cost-note">Both speed numbers are Artificial Analysis medians. Time to first token uses a log axis because the measured waits span from about one second to several minutes.</p>}

        {pinnedRows.length ? <section className="performance-comparison" aria-label="Pinned model comparison">
          <div className="performance-table-scroll"><table>
            <thead><tr><th scope="col">Measure</th>{pinnedRows.map((row) => <th key={row.model.key} scope="col">
              <div><Link to={{ pathname: `/models/${encodeURIComponent(row.model.key)}`, search: location.search }}>{row.model.name}</Link>
                <button type="button" title={`Unpin ${row.model.name}`} aria-label={`Unpin ${row.model.name}`} onClick={() => togglePin(row.model.key)}><X size={14} /></button></div>
            </th>)}</tr></thead>
            <tbody>
              <tr><th scope="row">{explorer === 'speed' ? SPEED_LABELS[speedMetric] : COST_LABELS[costMetric]}</th>{pinnedRows.map((row) => <td key={row.model.key}>{explorer === 'speed' ? formatSpeed(speedValue(row, speedMetric), speedMetric) : formatCurrency(costValue(row, costMetric), 4)}</td>)}</tr>
              {PERFORMANCE_METRICS.map((metric) => <tr key={metric}><th scope="row">{PERFORMANCE_LABELS[metric]}</th>
                {pinnedRows.map((row) => <td key={row.model.key}>{formatPerformance(performanceValue(row, metric), metric)}</td>)}
              </tr>)}
            </tbody>
          </table></div>
        </section> : null}

        <div className="performance-layout">
          <div className="performance-main">
            {explorer === 'speed' ? <div className="performance-stage">
              <div className="performance-stack">
                <section className="performance-panel" aria-labelledby="speed-heading">
                  <header><div><h2 id="speed-heading">{SPEED_LABELS[speedMetric]}</h2></div>
                    <span>{speedComparison.points.length} plotted / {speedComparison.omitted} omitted</span></header>
                  {speedComparison.points.length ? <>
                    <div className="performance-chart-frame"><PerformanceVsCostChart model={speedComparison} variant="interactive"
                      scoreLabel={PERFORMANCE_LABELS[metric]} costLabel={SPEED_LABELS[speedMetric]}
                      costScale={speedMetric === 'ttft' ? 'log' : 'linear'} xDomain={speedComparison.xDomain}
                      providers={providers} hoverKey={hoverKey} pinnedKeys={pinnedKeys}
                      brushedKeys={brushedKeys} onHover={setHoverKey} onSelect={togglePin}
                      brushMode={brushMode} brushReset={scatterBrushReset}
                      xBetter={speedMetric === 'output' ? 'higher' : 'lower'} showScale={false}
                      formatX={formatSpeedAxis}
                      onBrush={(keys) => {
                        setAxisBrushes({})
                        setParallelBrushReset((value) => value + 1)
                        setScatterBrushKeys(keys)
                        setBrushSource(null)
                      }} />
                    </div>
                    <div className="performance-frontier" aria-label="Speed Pareto front">
                      <span className="performance-frontier__label">Pareto front</span>
                      {speedComparison.pareto.map((point) => <button key={point.key} type="button"
                        aria-pressed={pinnedKeys.includes(point.key)} onClick={() => togglePin(point.key)}
                        onPointerEnter={() => setHoverKey(point.key)} onPointerLeave={() => setHoverKey(null)}
                        onFocus={() => setHoverKey(point.key)} onBlur={() => setHoverKey(null)}>{point.name}</button>)}
                    </div>
                  </> : <EmptyState message={`No measured ${PERFORMANCE_LABELS[metric]} and ${SPEED_LABELS[speedMetric]} pairs for this selection.`} />}
                </section>
              </div>
              <section className="performance-panel performance-panel--parallel" aria-labelledby="parallel-heading">
                <header>
                  <div>
                    <h2 id="parallel-heading">Parallel coordinates</h2>
                    {pinnedRows.length ? <ul className="performance-pin-legend">
                      {pinnedRows.map((row, index) => <li key={row.model.key}>
                        <span style={{ background: COMPARE_STROKES[index] }} />{row.model.name}
                      </li>)}
                    </ul> : null}
                  </div>
                  <span>Cohort in gray</span>
                </header>
                <p className="performance-axis-note">Each axis keeps its own scale. Performance points upward. Speed is oriented so a higher position is faster.</p>
                <div className="performance-chart-frame">
                  <ParallelCoordinatesChart records={speedRecords} axes={SPEED_PARALLEL_AXES}
                    costScale={speedMetric === 'ttft' ? 'log' : 'linear'} costDomain={speedComparison.xDomain}
                    costLabel={SPEED_LABELS[speedMetric]} lowerIsBetter={speedMetric === 'ttft'}
                    formatLead={formatSpeedAxis}
                    leadTitle={speedMetric === 'output' ? 'Output speed' : 'TTFT'} leadHint="faster ↑"
                    hoverKey={hoverKey} pinnedKeys={pinnedKeys}
                    brushedKeys={brushedKeys} brushReset={parallelBrushReset}
                    onHover={setHoverKey} onSelect={togglePin} onAxisBrush={brushAxis} />
                </div>
              </section>
            </div> : <>
            <div className={`performance-stage${layout === 'compare' ? ' performance-stage--compare' : ''}`}>
              <div className="performance-stack">
                {activeMetrics.map((item, index) => {
                  const model = comparison.models[item]
                  return <section className="performance-panel" key={item} aria-labelledby={`performance-${item}-heading`}>
                    <header><div>{layout === 'compare' ? <span className="performance-panel__number">0{index + 1}</span> : null}
                      <h2 id={`performance-${item}-heading`}>{PERFORMANCE_LABELS[item]}</h2></div>
                      <span>{model.points.length} plotted / {model.omitted} omitted</span></header>
                    {model.points.length ? <>
                      <div className="performance-chart-frame"><PerformanceVsCostChart model={model} variant="interactive"
                        scoreLabel={PERFORMANCE_LABELS[item]} costLabel={costMetric === 'task' ? 'AA cost / Intelligence task (USD)' : COST_LABELS[costMetric]}
                        costScale={costScale} xDomain={comparison.xDomain} providers={providers}
                        hoverKey={hoverKey} pinnedKeys={pinnedKeys} brushedKeys={brushedKeys}
                        onHover={setHoverKey} onSelect={togglePin} brushMode={brushMode}
                        brushReset={scatterBrushReset + viewBrushResets[item]}
                        onBrush={(keys) => {
                          setAxisBrushes({})
                          setParallelBrushReset((value) => value + 1)
                          setScatterBrushKeys(keys)
                          if (brushSource !== item) setViewBrushResets((current) => ({
                            intelligence: current.intelligence + (item === 'intelligence' ? 0 : 1),
                            coding: current.coding + (item === 'coding' ? 0 : 1),
                            agent: current.agent + (item === 'agent' ? 0 : 1),
                          }))
                          setBrushSource(keys === null ? null : item)
                        }} />
                      </div>
                      <div className="performance-frontier" aria-label={`${PERFORMANCE_LABELS[item]} Pareto front`}>
                        <span className="performance-frontier__label">Pareto front</span>
                        {model.pareto.map((point) => <button key={point.key} type="button"
                          aria-pressed={pinnedKeys.includes(point.key)} onClick={() => togglePin(point.key)}
                          onPointerEnter={() => setHoverKey(point.key)} onPointerLeave={() => setHoverKey(null)}
                          onFocus={() => setHoverKey(point.key)} onBlur={() => setHoverKey(null)}>{point.name}</button>)}
                      </div>
                    </> : <EmptyState message={`No measured ${PERFORMANCE_LABELS[item]} and cost pairs for this selection.`} />}
                  </section>
                })}
                {!activeMetrics.length ? <EmptyState message="No views selected." /> : null}
              </div>
              <section className="performance-panel performance-panel--parallel" aria-labelledby="parallel-heading">
                <header>
                  <div>
                    <h2 id="parallel-heading">Parallel coordinates</h2>
                    {pinnedRows.length ? <ul className="performance-pin-legend">
                      {pinnedRows.map((row, index) => <li key={row.model.key}>
                        <span style={{ background: COMPARE_STROKES[index] }} />{row.model.name}
                      </li>)}
                    </ul> : null}
                  </div>
                  <span>Cohort in gray</span>
                </header>
                <p className="performance-axis-note">Each axis keeps its own scale. Performance points upward. Cost is reversed, so a higher position is cheaper.</p>
                <div className="performance-chart-frame">
                  <ParallelCoordinatesChart records={records} costScale={costScale} costDomain={comparison.xDomain}
                    costLabel={COST_LABELS[costMetric]} hoverKey={hoverKey} pinnedKeys={pinnedKeys}
                    brushedKeys={brushedKeys} brushReset={parallelBrushReset}
                    onHover={setHoverKey} onSelect={togglePin} onAxisBrush={brushAxis} />
                </div>
              </section>
            </div>
            </>}
            <section className="performance-panel" aria-labelledby="rank-heading">
              <header>
                <div><h2 id="rank-heading">Rank comparison</h2></div>
                <span>Rank 1 is best</span>
              </header>
              <p className="performance-axis-note">Ranks are computed inside the current provider filter. Ties share a rank. This compares order, not the size of the score gap.</p>
              {rankSeries.length ? <div className="performance-chart-frame performance-chart-frame--short">
                <RankBumpChart series={rankSeries} cohortSize={comparison.rows.length} />
              </div> : <EmptyState title="Pin models to compare ranks" message="Pin two or three models to see how their ranks change across Intelligence, Coding, and Agent." />}
            </section>
          </div>

          <aside className="performance-aside">
            <section className="performance-details" aria-label="Model details">
              <p className="performance-eyebrow">{inspected ? providerLabel(inspected.model.organization) : 'Model details'}</p>
              <h2>{inspected?.model.name ?? 'No model selected'}</h2>
              {inspected ? <>
                {!comparison.rows.some((row) => row.model.key === inspected.model.key) ? <p className="performance-muted">Outside the current provider filter.</p> : null}
                <dl>
                  <div><dt>{explorer === 'speed' ? SPEED_LABELS[speedMetric] : COST_LABELS[costMetric]}</dt>
                    <dd>{explorer === 'speed'
                      ? formatSpeed(speedValue(inspected, speedMetric), speedMetric)
                      : formatCurrency(costValue(inspected, costMetric), 4)}
                      {explorer === 'speed' ? <small>{speedComparison.pareto.some((point) => point.key === inspected.model.key)
                        ? 'On Pareto front' : speedComparison.points.some((point) => point.key === inspected.model.key)
                          ? 'Off Pareto front' : 'Not plotted in current cohort'}</small> : null}</dd></div>
                  {PERFORMANCE_METRICS.map((metric) => <div key={metric}>
                    <dt>{PERFORMANCE_LABELS[metric]}</dt><dd>{formatPerformance(performanceValue(inspected, metric), metric)}
                      <small>{comparison.models[metric].points.some((point) => point.key === inspected.model.key)
                        ? comparison.models[metric].pareto.some((point) => point.key === inspected.model.key) ? 'On Pareto front' : 'Off Pareto front'
                        : 'Not plotted in current cohort'}</small></dd>
                  </div>)}
                </dl>
                <p className="performance-updated">AA updated {formatDateTime(inspected.aa.last_synced_at)}<br />
                  LMArena published {inspected.categories.agent.leaderboard_publish_date ?? 'Not reported'}<br />
                  Intelligence Index version {inspected.aa.intelligence_index_version ?? 'Not reported'}</p>
                <div className="performance-details__actions">
                  <button type="button" onClick={() => togglePin(inspected.model.key)}
                    aria-pressed={pinnedKeys.includes(inspected.model.key)}><Pin size={14} />
                    {pinnedKeys.includes(inspected.model.key) ? 'Unpin model' : 'Pin model'}</button>
                  <Link to={{ pathname: `/models/${encodeURIComponent(inspected.model.key)}`, search: location.search }}>
                    Model page<ArrowUpRight size={14} /></Link>
                </div>
              </> : null}
            </section>
            <section className="performance-models" aria-label="Models in selection">
              <h2>Models <span>{listedRows.length}</span></h2>
              <div className="performance-model-list">
                {listedRows.map((row) => <button type="button" key={row.model.key}
                  aria-label={`Pin ${row.model.name}`} aria-pressed={pinnedKeys.includes(row.model.key)}
                  onClick={() => togglePin(row.model.key)}
                  onPointerEnter={() => setHoverKey(row.model.key)} onPointerLeave={() => setHoverKey(null)}
                  onFocus={() => setHoverKey(row.model.key)} onBlur={() => setHoverKey(null)}>
                  <span className="performance-swatch" style={{ background: providerColor(row.model.organization ?? 'unknown', providers) }} />
                  <span>{row.model.name}<small>{providerLabel(row.model.organization)}</small></span>
                  {pinnedKeys.includes(row.model.key) ? <Pin size={13} /> : null}
                </button>)}
                {!listedRows.length ? <p className="performance-muted">No models in this selection.</p> : null}
              </div>
            </section>
          </aside>
        </div>
        <p className="performance-source-note">{explorer === 'cost'
          ? 'Sources: Artificial Analysis and LMArena. The dashed line is the Pareto front for the selected performance score. The shaded region is below median cost and above median performance. Brushing highlights models without changing that reference cohort.'
          : 'Source: Artificial Analysis medians. The dashed line marks models that no other plotted model is both faster and more capable than. The shaded region is the fast, high-scoring side of the medians. Pins stay when you switch back to cost.'}</p>
      </> : null}
    </main>
  )
}
