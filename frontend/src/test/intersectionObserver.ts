/**
 * A controllable `IntersectionObserver` for jsdom.
 *
 * jsdom does not implement one, and the reader's rule-5 behaviour — the comment
 * being read is highlighted in both panes — has no other way to be tested. The
 * real API reports asynchronously on scroll; this makes the report a call the
 * test makes, so the assertion is about our logic rather than about timing.
 *
 * Installed unconditionally rather than only when missing, so the behaviour of
 * the suite does not depend on which jsdom version happens to ship one.
 */
export class IntersectionObserverStub {
  /** The most recently constructed observer — components make exactly one. */
  static latest: IntersectionObserverStub | null = null

  observed: Element[] = []
  private readonly callback: IntersectionObserverCallback

  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
    IntersectionObserverStub.latest = this
  }

  observe(target: Element): void {
    if (!this.observed.includes(target)) this.observed.push(target)
  }

  unobserve(target: Element): void {
    this.observed = this.observed.filter((element) => element !== target)
  }

  disconnect(): void {
    this.observed = []
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  /**
   * Report `target` as the only element inside the reading band, and everything
   * else as outside it — which is what a real observation would say after a
   * scroll, and what makes the "topmost intersecting" pick deterministic.
   */
  enter(target: Element): void {
    const entries = this.observed.map(
      (element) =>
        ({
          target: element,
          isIntersecting: element === target,
          intersectionRatio: element === target ? 1 : 0,
        }) as unknown as IntersectionObserverEntry,
    )
    this.callback(entries, this as unknown as IntersectionObserver)
  }
}

export function installIntersectionObserver(): void {
  globalThis.IntersectionObserver =
    IntersectionObserverStub as unknown as typeof IntersectionObserver
}

export function resetIntersectionObserver(): void {
  IntersectionObserverStub.latest = null
}
