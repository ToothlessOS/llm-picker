import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight } from 'lucide-react'
import type { ComponentType } from 'react'
import { Link, useLocation } from 'react-router-dom'

import { getMetadata } from '../../api'
import { formatDateTime } from '../../app/format'
import { CostPerTaskPreview } from '../visualizations/CostPerTaskPreview'
import { ModelCardPreview } from '../visualizations/ModelCardPreview'
import { PerformanceVsCostPreview } from '../visualizations/PerformanceVsCostPreview'
import { TaskFitPreview } from '../visualizations/TaskFitPreview'

interface VisualizationSummary {
  title: string
  question: string
  encoding: string
  source: string
  path: string
  Preview: ComponentType
}

const visualizations: VisualizationSummary[] = [
  {
    title: 'Performance vs. cost',
    question: 'Which models offer the strongest capability at a given price?',
    encoding:
      'Position maps cost per task and intelligence; color identifies provider, and the frontier marks efficient choices.',
    source: 'Artificial Analysis models joined to LMArena agent entries.',
    path: '/visualizations/performance-vs-cost',
    Preview: PerformanceVsCostPreview,
  },
  {
    title: 'Cost per task',
    question: 'How much does each model cost for a comparable workload?',
    encoding:
      'Bar height maps estimated cost per task, with segments showing the input and output list-price mix.',
    source: 'Artificial Analysis pricing and token estimates.',
    path: '/visualizations/cost-per-task',
    Preview: CostPerTaskPreview,
  },
  {
    title: 'Task fit',
    question: 'Which models perform best for agent, document, search, and web development tasks?',
    encoding:
      'Rows represent models, columns represent task leaderboards, and color maps relative rank within each task.',
    source: 'LMArena task leaderboards for complete matched models.',
    path: '/visualizations/task-fit',
    Preview: TaskFitPreview,
  },
  {
    title: 'Model card',
    question: 'Where is a selected model strong or weak relative to its peers?',
    encoding:
      'Radar axes map percentile scores for capability, task fit, and cost efficiency against the cohort median.',
    source: 'Joined LMArena and Artificial Analysis model records.',
    path: '/visualizations/model-card',
    Preview: ModelCardPreview,
  },
]

const processingSteps = [
  {
    title: 'Validate',
    detail: 'Check source schemas and preserve missing measurements as null values.',
  },
  {
    title: 'Normalize',
    detail: 'Normalize names with Unicode NFKC, case folding, and punctuation removal.',
  },
  {
    title: 'Deduplicate',
    detail: 'Keep the best-ranked web development row and retain AA reasoning variants.',
  },
  {
    title: 'Match',
    detail: 'Join exact keys, names, slugs, aliases, and approved harness variants.',
  },
  {
    title: 'Refresh',
    detail: 'Upsert transactionally and deactivate records absent from the latest snapshot.',
  },
] as const

const interactionRows = [
  {
    visualization: 'Performance vs. cost',
    interaction: 'Hover to inspect a model, focus a provider, and open model details.',
    animation: 'Transition points and the Pareto frontier when filters change.',
    purpose: 'Reveal tradeoffs and make efficient alternatives easier to compare.',
  },
  {
    visualization: 'Cost per task',
    interaction: 'Hover for exact prices and select a bar to inspect its model.',
    animation: 'Grow and reorder bars smoothly when the metric or filter changes.',
    purpose: 'Support accurate cost comparison without losing ranking context.',
  },
  {
    visualization: 'Task fit',
    interaction: 'Inspect cells, choose a task to sort by, and open a model.',
    animation: 'Animate row reordering while keeping the selected task anchored.',
    purpose: 'Show how the recommended model changes with the intended job.',
  },
  {
    visualization: 'Model card',
    interaction: 'Select a model and inspect each dimension against the median.',
    animation: 'Interpolate the radar shape and labels between model selections.',
    purpose: 'Make multidimensional strengths and weaknesses easier to recognize.',
  },
] as const

const numberFormatter = new Intl.NumberFormat()

export function InterimCheckInPage() {
  const location = useLocation()
  const metadataQuery = useQuery({
    queryKey: ['metadata'],
    queryFn: ({ signal }) => getMetadata({ signal }),
    refetchInterval: 60_000,
  })
  const metadata = metadataQuery.data
  const counts = metadata?.counts

  const liveStats = [
    { label: 'LMArena records', value: counts?.lmarena_entries },
    { label: 'AA variants', value: counts?.aa_models },
    { label: 'Agent leaderboard entries', value: counts?.lmarena_agent_entries },
    { label: 'Complete joins', value: counts?.complete_agent_entries },
  ]

  return (
    <main className="interim-page">

      <header className="interim-hero">
        <p className="home-kicker">STATS 401 / Interim checkpoint</p>
        <h1>Interim check-in</h1>
        <nav aria-label="On this page" className="interim-jump-nav">
          <a href="#dataset">Dataset</a>
          <a href="#visualizations-check-in">Visualizations</a>
          <a href="#interaction-plan">Interaction plan</a>
          <a href="#evaluation-plan">Evaluation plan</a>
        </nav>
      </header>

      <section
        aria-labelledby="dataset-heading"
        className="interim-section"
        id="dataset"
      >
        <header className="interim-section__heading">
          <span aria-hidden="true">01</span>
          <div>
            <h2 id="dataset-heading">Dataset</h2>
            <p>
              Two external model datasets are retained separately, cleaned,
              and joined only when identity can be established without fuzzy matching.
            </p>
          </div>
        </header>

        <div className="interim-source-grid">
          <article className="interim-source">
            <p className="interim-label">Raw source 01</p>
            <h3>LMArena</h3>
            <p>
              The latest agent, document, search, and web development leaderboards
              provide task-specific ranks, ratings, scores, and publication dates.
            </p>
            <p className="interim-source__meta">
              Last successful update:{' '}
              <strong>{formatDateTime(metadata?.sources.lmarena.last_success_at)}</strong>
            </p>
          </article>
          <article className="interim-source">
            <p className="interim-label">Raw source 02</p>
            <h3>Artificial Analysis</h3>
            <p>
              The API catalog supplies intelligence scores, list prices, speed,
              latency, and estimated cost per task for model variants.
            </p>
            <p className="interim-source__meta">
              Last successful update:{' '}
              <strong>
                {formatDateTime(metadata?.sources.artificial_analysis.last_success_at)}
              </strong>
            </p>
          </article>
        </div>

        <div aria-label="Current processed dataset counts" className="interim-stat-grid">
          {liveStats.map((stat) => (
            <div className="interim-stat" key={stat.label}>
              <strong>
                {stat.value === undefined ? '--' : numberFormatter.format(stat.value)}
              </strong>
              <span>{stat.label}</span>
            </div>
          ))}
        </div>
        {metadataQuery.isError ? (
          <p className="interim-inline-status" role="status">
            Live counts are temporarily unavailable. The source and processing
            descriptions remain current.
          </p>
        ) : null}

        <div className="interim-subsection-heading">
          <p className="interim-label">Cleaning and processing</p>
          <h3>From source snapshots to comparable records</h3>
        </div>
        <ol className="interim-pipeline">
          {processingSteps.map((step) => (
            <li key={step.title}>
              <h4>{step.title}</h4>
              <p>{step.detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section
        aria-labelledby="visualizations-heading"
        className="interim-section"
        id="visualizations-check-in"
      >
        <header className="interim-section__heading">
          <span aria-hidden="true">02</span>
          <div>
            <h2 id="visualizations-heading">Visualizations</h2>
            <p>
              Four implemented views render the current project data. Each preview
              opens the full visualization for closer inspection.
            </p>
          </div>
        </header>

        <div className="interim-viz-grid">
          {visualizations.map(({ Preview, ...visualization }) => {
            const titleId = `interim-${visualization.path.split('/').at(-1)}-title`
            return (
              <Link
                aria-labelledby={titleId}
                className="interim-viz"
                key={visualization.path}
                to={{ pathname: visualization.path, search: location.search }}
              >
                <header>
                  <div>
                    <h3 id={titleId}>{visualization.title}</h3>
                    <p>{visualization.question}</p>
                  </div>
                  <span className="viz-stage__action">
                    Open interactive
                    <ArrowUpRight aria-hidden="true" size={16} />
                  </span>
                </header>
                <Preview />
                <dl className="interim-viz__details">
                  <div>
                    <dt>Encoding</dt>
                    <dd>{visualization.encoding}</dd>
                  </div>
                  <div>
                    <dt>Data</dt>
                    <dd>{visualization.source}</dd>
                  </div>
                </dl>
              </Link>
            )
          })}
        </div>
      </section>

      <section
        aria-labelledby="interaction-heading"
        className="interim-section"
        id="interaction-plan"
      >
        <header className="interim-section__heading">
          <span aria-hidden="true">03</span>
          <div>
            <h2 id="interaction-heading">Interaction / Animation Plan</h2>
            <p>
              Interaction will expose exact values and support comparison; motion
              will preserve context as the displayed model set changes.
            </p>
          </div>
        </header>

        <div className="interim-table-wrap">
          <table className="interim-plan-table">
            <thead>
              <tr>
                <th scope="col">Visualization</th>
                <th scope="col">Interaction</th>
                <th scope="col">Animation</th>
                <th scope="col">Purpose</th>
              </tr>
            </thead>
            <tbody>
              {interactionRows.map((row) => (
                <tr key={row.visualization}>
                  <th scope="row">{row.visualization}</th>
                  <td>{row.interaction}</td>
                  <td>{row.animation}</td>
                  <td>{row.purpose}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section
        aria-labelledby="evaluation-heading"
        className="interim-section"
        id="evaluation-plan"
      >
        <header className="interim-section__heading">
          <span aria-hidden="true">04</span>
          <div>
            <h2 id="evaluation-heading">Evaluation Plan</h2>
            <p>
              A task-based usability study will test whether the visualizations help
              people make accurate, confident model choices.
            </p>
          </div>
        </header>

        <div className="interim-evaluation-grid">
          <article>
            <p className="interim-label">What we will evaluate</p>
            <h3>Understanding and utility</h3>
            <p>
              Task accuracy, comparison speed, interaction discoverability, trust
              in missing values, and overall usability.
            </p>
          </article>
          <article>
            <p className="interim-label">How we will evaluate</p>
            <h3>Scenario-based study</h3>
            <p>
              Eight to twelve LLM users will complete four model-selection tasks
              using think-aloud, post-task ratings, SUS, and a short interview.
            </p>
          </article>
          <article>
            <p className="interim-label">What we will collect</p>
            <h3>Behavior and feedback</h3>
            <p>
              Completion, accuracy, time, navigation path, misclicks, confidence,
              ease ratings, SUS scores, and open-ended comments.
            </p>
          </article>
        </div>

      </section>
    </main>
  )
}
