import { Link, useLocation } from 'react-router-dom'

const visualizations = [
  {
    title: 'Performance vs. cost',
    question: 'Who is best at this price?',
    forthcoming:
      'Scatter of intelligence vs cost per task, with a dashed Pareto front.',
  },
  {
    title: 'Cost per task',
    question: 'Where does the money go?',
    forthcoming:
      'Stacked bars of input, output, and cache cost per intelligence-index task.',
  },
  {
    title: 'Task fit',
    question: 'Which model fits the job?',
    forthcoming:
      'Comparison across agent, document, search, and webdev. Replaces the unpublished battle heatmap.',
  },
  {
    title: 'Model card',
    question: 'How does this model compare?',
    forthcoming:
      'Radar of intelligence, coding, agentic, cost, and speed versus the cohort average.',
  },
] as const

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
          {visualizations.map((item) => (
            <article className="viz-stage" key={item.title}>
              <header>
                <h2>{item.title}</h2>
                <p>{item.question}</p>
              </header>
              <div
                aria-label={`${item.title} placeholder`}
                className="viz-stage__canvas"
                role="img"
              >
                <p>{item.forthcoming}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <p className="survey-note">People like you — coming soon</p>
    </main>
  )
}
