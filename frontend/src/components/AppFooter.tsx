import type { MetadataResponse } from '../api'

interface AppFooterProps {
  metadata?: MetadataResponse
}

export function AppFooter({ metadata }: AppFooterProps) {
  const attribution = metadata?.attribution

  return (
    <footer className="app-footer">
      <div className="app-footer__inner">
        <p>LLM Picker</p>
        <nav aria-label="Sources">
          {attribution?.lmarena ? (
            <a href={attribution.lmarena} rel="noreferrer" target="_blank">
              LMArena
            </a>
          ) : (
            <span>LMArena</span>
          )}
          <span aria-hidden="true">·</span>
          {attribution?.artificial_analysis ? (
            <a
              href={attribution.artificial_analysis}
              rel="noreferrer"
              target="_blank"
            >
              Artificial Analysis
            </a>
          ) : (
            <span>Artificial Analysis</span>
          )}
        </nav>
      </div>
    </footer>
  )
}
