import { copyFileSync } from 'node:fs'
import { join } from 'node:path'

import react from '@vitejs/plugin-react'
import { loadEnv, type Plugin } from 'vite'
import { defineConfig } from 'vitest/config'

/**
 * GitHub Pages serves a *project* site under `/<repo>/`, and `actions/configure-pages`
 * reports that prefix with no trailing slash. Vite's own `resolveBaseUrl` does not
 * add one either, so normalize here rather than leaving it to chance: a base
 * without the trailing slash leaks into `import.meta.env.BASE_URL` and into
 * Vite's internal URL joining.
 */
function normalizeBase(value: string | undefined): string {
  const raw = (value ?? '').trim()
  if (raw === '' || raw === '/') return '/'
  return `${raw.replace(/\/+$/, '')}/`
}

/**
 * Pages has no rewrite rules, so a hard load of `/llm-picker/models/x/` is
 * answered with `404.html`. Copying the built `index.html` there makes that
 * response the app shell, which boots *at* the original URL and lets the router
 * resolve the route -- no redirect, nothing to restore.
 *
 * This works only because Vite emits *absolute* `/llm-picker/assets/...` URLs. A
 * relative base (`./`) would resolve against the deep path and 404.
 */
function spaFallback(): Plugin {
  let outDir = ''
  return {
    name: 'spa-404-fallback',
    apply: 'build', // skipped by vitest
    configResolved(config) {
      outDir = config.build.outDir
    },
    closeBundle() {
      copyFileSync(join(outDir, 'index.html'), join(outDir, '404.html'))
    },
  }
}

export default defineConfig(({ mode }) => {
  // Reads `VITE_BASE_PATH` from a `.env` file *or* the process environment -- CI
  // sets it from `configure-pages`, while a developer can drop it in `.env.local`
  // to reproduce the Pages subpath locally without touching this file.
  const env = loadEnv(mode, process.cwd())

  return {
    base: normalizeBase(env.VITE_BASE_PATH),
    plugins: [react(), spaFallback()],
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
