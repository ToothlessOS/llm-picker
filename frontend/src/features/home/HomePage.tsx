import { ArrowUpRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { CostPerTaskPreview } from '../visualizations/CostPerTaskPreview'
import { ModelCardPreview } from '../visualizations/ModelCardPreview'
import { PerformanceVsCostPreview } from '../visualizations/PerformanceVsCostPreview'
import { TaskFitPreview } from '../visualizations/TaskFitPreview'

const dataLinks = [
  { to: '/models', title: 'Models', blurb: 'Complete matched table' },
  { to: '/categories', title: 'Categories', blurb: 'Task leaderboards' },
  { to: '/artificial-analysis', title: 'AA Models', blurb: 'Full AA catalog' },
  { to: '/data-quality', title: 'Data quality', blurb: 'Matching and freshness' },
] as const

export function HomePage() {
  const location = useLocation()

  return (
    <main className="home">
      <section className="home-section home-section--data" aria-labelledby="data-heading">
        <p className="home-kicker" id="data-heading">
          Data
        </p>
        <div className="data-row">
          {dataLinks.map((item) => (
            <Link
              className="data-tile"
              key={item.to}
              to={{ pathname: item.to, search: location.search }}
            >
              <h2>{item.title}</h2>
              <p>{item.blurb}</p>
            </Link>
          ))}
        </div>
      </section>

      <section className="home-hero">
        <p className="home-kicker">STATS 401 · Final project</p>
        <h1>
          Which model is worth
          <br />
          the <em>price.</em>
        </h1>
        <p className="home-lede">
          Compare cost, capability, and task fit.
        </p>
        <a className="hero-cta" href="#visualizations">
          See the charts
        </a>
      </section>

      <section className="home-section" id="visualizations">
        <p className="home-kicker">Visualizations</p>
        <div className="viz-gallery">
          <Link
            aria-labelledby="viz-performance-cost-title"
            className="viz-stage viz-stage--link"
            to={{ pathname: '/visualizations/performance-vs-cost', search: location.search }}
          >
            <header>
              <div>
                <h2 id="viz-performance-cost-title">Performance vs. cost</h2>
                <p>Who is best at this price?</p>
              </div>
              <span className="viz-stage__action">
                Open interactive
                <ArrowUpRight aria-hidden="true" size={16} />
              </span>
            </header>
            <PerformanceVsCostPreview />
          </Link>
          <Link
            aria-labelledby="viz-cost-per-task-title"
            className="viz-stage viz-stage--link"
            to={{ pathname: '/visualizations/cost-per-task', search: location.search }}
          >
            <header>
              <div>
                <h2 id="viz-cost-per-task-title">Cost per task</h2>
                <p>Where does the money go? Split by list prices, not usage.</p>
              </div>
              <span className="viz-stage__action">
                Open interactive
                <ArrowUpRight aria-hidden="true" size={16} />
              </span>
            </header>
            <CostPerTaskPreview />
          </Link>
          <Link
            aria-labelledby="viz-task-fit-title"
            className="viz-stage viz-stage--link"
            to={{ pathname: '/visualizations/task-fit', search: location.search }}
          >
            <header>
              <div>
                <h2 id="viz-task-fit-title">Task fit</h2>
                <p>Which model fits the job?</p>
              </div>
              <span className="viz-stage__action">
                Open interactive
                <ArrowUpRight aria-hidden="true" size={16} />
              </span>
            </header>
            <TaskFitPreview />
          </Link>
          <Link
            aria-labelledby="viz-model-card-title"
            className="viz-stage viz-stage--link"
            to={{ pathname: '/visualizations/model-card', search: location.search }}
          >
            <header>
              <div>
                <h2 id="viz-model-card-title">Model card</h2>
                <p>How does this model compare?</p>
              </div>
              <span className="viz-stage__action">
                Open interactive
                <ArrowUpRight aria-hidden="true" size={16} />
              </span>
            </header>
            <ModelCardPreview />
          </Link>
        </div>
      </section>

      <p className="survey-note">People like you — coming soon</p>
    </main>
  )
}
