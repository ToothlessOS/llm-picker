import { StrictMode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { queryClient } from './app/queryClient.ts'
import { startThemeClock } from './app/theme.ts'

startThemeClock()

// Vite injects the configured `base` here, always with a trailing slash -- `/`
// locally, `/llm-picker/` on GitHub Pages. react-router wants the basename
// without one, and '' is how it spells "no basename".
const basename = import.meta.env.BASE_URL.replace(/\/+$/, '')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={basename}>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
