import { Star } from 'lucide-react'

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
            <a href={attribution.artificial_analysis} rel="noreferrer" target="_blank">
              Artificial Analysis
            </a>
          ) : (
            <span>Artificial Analysis</span>
          )}
        </nav>
        <p className="app-footer__note">{'Come poke around on '}<a href="https://github.com/ToothlessOS/llm-picker" rel="noreferrer" target="_blank">GitHub</a>{', a little '}<em><Star aria-hidden="true" size={13} />star</em>{' would make our day.'}</p>
      </div>
    </footer>
  )
}
