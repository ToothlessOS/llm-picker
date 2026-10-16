import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

import {
  installIntersectionObserver,
  resetIntersectionObserver,
} from './intersectionObserver'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof globalThis.ResizeObserver === 'undefined') {
  globalThis.ResizeObserver = ResizeObserverStub
}

// The reader uses an IntersectionObserver to follow the reading position, and
// jsdom has none. See `intersectionObserver.ts` for why this is installed
// unconditionally rather than only when absent.
installIntersectionObserver()

afterEach(() => {
  resetIntersectionObserver()
  cleanup()
})
