import { useMemo, useState } from 'react'
import { ArrowLeft, ArrowUpRight, MousePointer2, Pin, RotateCcw, SquareDashedMousePointer, X } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import type { OverviewRow } from '../../api'
import { formatCurrency, formatDateTime } from '../../app/format'
import { PageHeader } from '../../components/PageHeader'
import { EmptyState } from '../../components/states/EmptyState'
import { ErrorState } from '../../components/states/ErrorState'
import { LoadingState } from '../../components/states/LoadingState'
import { PerformanceVsCostChart } from './PerformanceVsCostChart'
import { providerColor, providerLabel } from './scatter'
import {
  buildPerformanceComparison, COST_LABELS, costValue, formatPerformance,
  PERFORMANCE_LABELS, PERFORMANCE_METRICS, performanceValue, toggleComparedModel,
  type CostMetric, type CostScale, type PerformanceMetric,
} from './performanceComparison'
import { useOverviewPerformance } from './useOverviewScatter'

export function PerformanceVsCostPage() {
  const location = useLocation()
  const query = useOverviewPerformance()
  const [costMetric, setCostMetric] = useState<CostMetric>('task')
  const [costScale, setCostScale] = useState<CostScale>('log')
  const [provider, setProvider] = useState<string | null>(null)
  const [views, setViews] = useState<PerformanceMetric[]>([...PERFORMANCE_METRICS])
  const [hoverKey, setHoverKey] = useState<string | null>(null)
  const [inspectedKey, setInspectedKey] = useState<string | null>(null)
  const [pinnedKeys, setPinnedKeys] = useState<string[]>([])
  const [brushedKeys, setBrushedKeys] = useState<string[] | null>(null)
  const [brushSource, setBrushSource] = useState<PerformanceMetric | null>(null)
  const [brushMode, setBrushMode] = useState(false)
  const [brushReset, setBrushReset] = useState(0)
  const [viewBrushResets, setViewBrushResets] = useState({ intelligence: 0, coding: 0, agent: 0 })
  const [message, setMessage] = useState('')
  const rows = query.data?.results
  const comparison = useMemo(() =>
    buildPerformanceComparison(rows ?? [], costMetric, costScale, provider),
  [rows, costMetric, costScale, provider])
  const providers = useMemo(() => [...new Set((rows ?? []).map((row) =>
    row.model.organization ?? 'unknown',
  ))].sort(), [rows])
  const inspected = rows?.find((row) => row.model.key === (hoverKey ?? inspectedKey ?? pinnedKeys.at(-1)))
  const pinnedRows = pinnedKeys.map((key) => rows?.find((row) => row.model.key === key))
    .filter((row): row is OverviewRow => row !== undefined)
  const visibleKeys = useMemo(() => new Set(PERFORMANCE_METRICS.flatMap((metric) =>
    comparison.models[metric].points.map((point) => point.key),
  )), [comparison])
  const listedRows = comparison.rows.filter((row) => visibleKeys.has(row.model.key) &&
    (brushedKeys === null || brushedKeys.includes(row.model.key)))

  const clearBrush = () => {
    setBrushedKeys(null)
    setBrushSource(null)
    setBrushReset((value) => value + 1)
  }
  const inspect = (key: string | null) => {
    setHoverKey(key)
    if (key) setInspectedKey(key)
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
      <PageHeader title="Performance vs. cost" count={rows?.length}
        isFetching={query.isFetching && !query.isPending}
        description="Capability and task performance against a common cost reference. Each view retains its original score and its own Pareto frontier." />
      {query.isPending ? <LoadingState label="Loading performance versus cost" rows={5} /> : null}
      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}
      {rows?.length === 0 ? <EmptyState message="No matched models are available." /> : null}

      {rows && rows.length > 0 ? <>
        <section className="performance-controls" aria-label="Comparison controls">
          <label className="performance-control performance-control--cost">
            <span>Cost reference</span>
            <select value={costMetric} onChange={(event) => { setCostMetric(event.target.value as CostMetric); clearBrush() }}>
              <option value="task">AA cost / Intelligence Index task</option>
              <option value="input">Input price / million tokens</option>
              <option value="output">Output price / million tokens</option>
            </select>
          </label>
          <fieldset className="performance-control">
            <legend>Cost scale</legend>
            <div className="performance-segmented">
              {(['log', 'linear'] as const).map((scale) => <label key={scale}>
                <input type="radio" name="cost-scale" value={scale} checked={costScale === scale}
                  onChange={() => { setCostScale(scale); clearBrush() }} />
                <span>{scale === 'log' ? 'Log' : 'Linear'}</span>
              </label>)}
            </div>
          </fieldset>
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
          <fieldset className="performance-views"><legend>Views</legend>
            {PERFORMANCE_METRICS.map((metric) => <label key={metric}>
              <input type="checkbox" checked={views.includes(metric)} onChange={() => toggleView(metric)} />
              {PERFORMANCE_LABELS[metric]}
            </label>)}
          </fieldset>
          <p className="performance-status" role="status">
            {message || (brushedKeys !== null ? `${brushedKeys.length} models brushed` : `${visibleKeys.size} models with measured cost`)}
            <span>{pinnedKeys.length} / 3 pinned</span>
            {brushedKeys !== null ? <button type="button" title="Clear brush" aria-label="Clear brush" onClick={clearBrush}><X size={14} /></button> : null}
          </p>
        </div>
        <p className="performance-cost-note">{costMetric === 'task'
          ? 'Cost is the AA Intelligence Index workload estimate, not a measured cost for Coding or LMArena Agent tasks.'
          : 'Token prices are AA list prices; they do not include model-specific token usage.'}
          {costScale === 'log' ? ' Zero and missing costs are omitted on the log axis.' : ' Missing costs are omitted; measured zero prices are included.'}</p>

        {pinnedRows.length ? <section className="performance-comparison" aria-label="Pinned model comparison">
          <div className="performance-table-scroll"><table>
            <thead><tr><th scope="col">Measure</th>{pinnedRows.map((row) => <th key={row.model.key} scope="col">
              <div><Link to={{ pathname: `/models/${encodeURIComponent(row.model.key)}`, search: location.search }}>{row.model.name}</Link>
                <button type="button" title={`Unpin ${row.model.name}`} aria-label={`Unpin ${row.model.name}`} onClick={() => togglePin(row.model.key)}><X size={14} /></button></div>
            </th>)}</tr></thead>
            <tbody>
              <tr><th scope="row">{COST_LABELS[costMetric]}</th>{pinnedRows.map((row) => <td key={row.model.key}>{formatCurrency(costValue(row, costMetric), 4)}</td>)}</tr>
              {PERFORMANCE_METRICS.map((metric) => <tr key={metric}><th scope="row">{PERFORMANCE_LABELS[metric]}</th>
                {pinnedRows.map((row) => <td key={row.model.key}>{formatPerformance(performanceValue(row, metric), metric)}</td>)}
              </tr>)}
            </tbody>
          </table></div>
        </section> : null}

        <div className="performance-layout">
          <div className="performance-stack">
            {PERFORMANCE_METRICS.filter((metric) => views.includes(metric)).map((metric, index) => {
              const model = comparison.models[metric]
              return <section className="performance-panel" key={metric} aria-labelledby={`performance-${metric}-heading`}>
                <header><div><span className="performance-panel__number">0{index + 1}</span>
                  <h2 id={`performance-${metric}-heading`}>{PERFORMANCE_LABELS[metric]}</h2></div>
                  <span>{model.points.length} plotted / {model.omitted} omitted</span></header>
                {model.points.length ? <>
                  <div className="performance-chart-frame"><PerformanceVsCostChart model={model} variant="interactive"
                    scoreLabel={PERFORMANCE_LABELS[metric]} costLabel={costMetric === 'task' ? 'AA cost / Intelligence task (USD)' : COST_LABELS[costMetric]}
                    costScale={costScale} xDomain={comparison.xDomain} providers={providers}
                    hoverKey={hoverKey} pinnedKeys={pinnedKeys} brushedKeys={brushedKeys}
                    onHover={inspect} onSelect={togglePin} brushMode={brushMode}
                    brushReset={brushReset + viewBrushResets[metric]}
                    onBrush={(keys) => {
                      setBrushedKeys(keys)
                      if (brushSource !== metric) setViewBrushResets((current) => ({
                        intelligence: current.intelligence + (metric === 'intelligence' ? 0 : 1),
                        coding: current.coding + (metric === 'coding' ? 0 : 1),
                        agent: current.agent + (metric === 'agent' ? 0 : 1),
                      }))
                      setBrushSource(keys === null ? null : metric)
                    }} />
                  </div>
                  <div className="performance-frontier" aria-label={`${PERFORMANCE_LABELS[metric]} Pareto front`}>
                    <span className="performance-frontier__label">Pareto front</span>
                    {model.pareto.map((point) => <button key={point.key} type="button"
                      aria-pressed={pinnedKeys.includes(point.key)} onClick={() => togglePin(point.key)}
                      onPointerEnter={() => inspect(point.key)} onPointerLeave={() => setHoverKey(null)}
                      onFocus={() => inspect(point.key)} onBlur={() => setHoverKey(null)}>{point.name}</button>)}
                  </div>
                </> : <EmptyState message={`No measured ${PERFORMANCE_LABELS[metric]} and cost pairs for this selection.`} />}
              </section>
            })}
            {!views.length ? <EmptyState message="No views selected." /> : null}
          </div>

          <aside className="performance-aside">
            <section className="performance-details" aria-label="Model details">
              <p className="performance-eyebrow">{inspected ? providerLabel(inspected.model.organization) : 'Model details'}</p>
              <h2>{inspected?.model.name ?? 'No model selected'}</h2>
              {inspected ? <>
                {!comparison.rows.some((row) => row.model.key === inspected.model.key) ? <p className="performance-muted">Outside the current provider filter.</p> : null}
                <dl>
                  <div><dt>{COST_LABELS[costMetric]}</dt><dd>{formatCurrency(costValue(inspected, costMetric), 4)}</dd></div>
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
                  onPointerEnter={() => inspect(row.model.key)} onPointerLeave={() => setHoverKey(null)}
                  onFocus={() => inspect(row.model.key)} onBlur={() => setHoverKey(null)}>
                  <span className="performance-swatch" style={{ background: providerColor(row.model.organization ?? 'unknown', providers) }} />
                  <span>{row.model.name}<small>{providerLabel(row.model.organization)}</small></span>
                  {pinnedKeys.includes(row.model.key) ? <Pin size={13} /> : null}
                </button>)}
                {!listedRows.length ? <p className="performance-muted">No models in this selection.</p> : null}
              </div>
            </section>
          </aside>
        </div>
        <p className="performance-source-note">Sources: Artificial Analysis and LMArena. Dashed lines mark each view's Pareto frontier within the current provider cohort. Shaded regions are below median cost and above median performance. Brushing highlights models without changing the reference cohort.</p>
      </> : null}
    </main>
  )
}
