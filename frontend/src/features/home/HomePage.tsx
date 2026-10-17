import { ArrowUpRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'

import { DiscussionMapPreview } from '../discussions/DiscussionMapPreview'
import { formatRelativeTime } from '../../app/format'
import { useLatestReleaseNotes } from '../visualizations/useOverviewScatter'
import { CommunityArt, CostBreakdownArt, ExplorerArt, ModelCardArt, TaskFitArt } from './HomeIllustrations'

const dataLinks = [
  { to: '/models', title: 'Models', blurb: 'Complete matched table' },
  { to: '/categories', title: 'Categories', blurb: 'Task leaderboards' },
  { to: '/artificial-analysis', title: 'AA Models', blurb: 'Full AA catalog' },
  { to: '/discussions', title: 'Discussions', blurb: 'LLM threads from Hacker News' },
  { to: '/data-quality', title: 'Data quality', blurb: 'Matching and freshness' },
] as const

export function HomePage() {
  const location = useLocation()
  const releases = useLatestReleaseNotes().data ?? []

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
        <div className="home-hero__copy">
          <p className="home-kicker">STATS 401 · Final project</p>
          <h1>
            Find the right model.
            <br />
            For your <em>task and budget.</em>
          </h1>
          <p className="home-lede">
            Explore capability, cost, and speed across leading LLMs.
          </p>
          <a className="hero-cta" href="#visualizations">
            See the charts
          </a>
        </div>

        {releases.length ? <section className="home-news" aria-labelledby="news-heading">
          <p className="home-kicker" id="news-heading">Just out</p>
          <ul>
            {releases.map((note, index) => (
              <li key={note.key}>
                <p>
                  {index === 0 ? <span className="home-news__mark" aria-hidden="true" /> : null}
                  <strong>{note.creator}</strong> just released <em>{note.name}</em>!
                </p>
                <time dateTime={note.releasedOn}>{formatRelativeTime(`${note.releasedOn}T00:00:00`)}</time>
              </li>
            ))}
          </ul>
        </section> : null}
      </section>

      <section className="home-section" id="visualizations">
        <p className="home-kicker">01 / Primary view</p>
        <Link
          aria-labelledby="viz-performance-title"
          className="viz-stage viz-stage--link viz-stage--feature"
          to={{ pathname: '/visualizations/performance-vs-cost', search: location.search }}
        >
          <header>
            <div>
              <h2 id="viz-performance-title">Performance explorer</h2>
              <p>Who is worth the price, and who is both fast and capable?</p>
            </div>
            <span className="viz-stage__action">
              Open interactive
              <ArrowUpRight aria-hidden="true" size={16} />
            </span>
          </header>
          <div className="home-explorer">
            <p className="home-explorer__switch"><span>Cost</span><span aria-hidden="true">|</span><span>Speed</span></p>
            <ExplorerArt />
          </div>
        </Link>
      </section>

      <section className="home-support" aria-labelledby="support-heading">
        <p className="home-kicker">02 / Supporting visualizations</p>
        <h2 id="support-heading">Explore further</h2>
        <p className="home-support__lede">Understand cost structure, task fit, and model profiles.</p>
        <div className="home-support__grid">
          <Link
            aria-labelledby="viz-cost-title"
            className="home-support__card"
            to={{ pathname: '/visualizations/cost-per-task', search: location.search }}
          >
            <p>01 / Cost analysis</p>
            <h3 id="viz-cost-title">Cost Breakdown</h3>
            <p>Where does the money go?</p>
            <CostBreakdownArt />
            <span>Explore costs <ArrowUpRight aria-hidden="true" size={14} /></span>
          </Link>
          <Link
            aria-labelledby="viz-task-title"
            className="home-support__card"
            to={{ pathname: '/visualizations/task-fit', search: location.search }}
          >
            <p>02 / Task comparison</p>
            <h3 id="viz-task-title">Task Fit</h3>
            <p>Which model fits the job?</p>
            <TaskFitArt />
            <span>Explore tasks <ArrowUpRight aria-hidden="true" size={14} /></span>
          </Link>
          <Link
            aria-labelledby="viz-card-title"
            className="home-support__card"
            to={{ pathname: '/visualizations/model-card', search: location.search }}
          >
            <p>03 / Model profile</p>
            <h3 id="viz-card-title">Model Card</h3>
            <p>How well-rounded is this model?</p>
            <ModelCardArt />
            <span>View model profiles <ArrowUpRight aria-hidden="true" size={14} /></span>
          </Link>
        </div>
      </section>

      <section className="home-community-wrap" id="people-like-you">
        <Link
          aria-labelledby="viz-discussion-title"
          className="home-community"
          to={{ pathname: '/discussions/map', search: location.search }}
        >
          <div>
            <p className="home-kicker">03 / Community insights</p>
            <h2 id="viz-discussion-title">What are people saying?</h2>
            <p className="home-community__lede">
              Explore opinions, discussions, and real-world experiences with popular LLMs.
            </p>
            <span>Explore discussion map <ArrowUpRight aria-hidden="true" size={14} /></span>
            <DiscussionMapPreview />
          </div>
          <div className="home-community__panel">
            <CommunityArt />
          </div>
        </Link>
      </section>
    </main>
  )
}
