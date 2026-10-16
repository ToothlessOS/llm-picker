export function formatDateTime(value: string | null | undefined): string {
  if (!value) return 'Not yet updated'

  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function formatNumber(value: number | null, digits = 1): string {
  if (value === null) return 'Not measured'
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: digits,
  }).format(value)
}

export function formatCurrency(value: number | null, digits = 2): string {
  if (value === null) return 'Not measured'
  return new Intl.NumberFormat(undefined, {
    currency: 'USD',
    maximumFractionDigits: digits,
    style: 'currency',
  }).format(value)
}

/**
 * A coarse "3 hours ago".
 *
 * Built on `Intl.RelativeTimeFormat`, so it reads correctly in any locale rather
 * than being an English suffix glued onto a number. Deliberately coarse: the
 * question a thread list answers is "is this current?", and "43 minutes ago"
 * carries no more of that than "an hour ago" while costing a column's width.
 */
export function formatRelativeTime(
  value: string | null | undefined,
  now: Date = new Date(),
): string {
  if (!value) return 'Unknown'
  const then = new Date(value)
  if (Number.isNaN(then.getTime())) return 'Unknown'

  const seconds = Math.round((then.getTime() - now.getTime()) / 1000)
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
  const steps: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
    ['year', 365 * 24 * 3600],
    ['month', 30 * 24 * 3600],
    ['week', 7 * 24 * 3600],
    ['day', 24 * 3600],
    ['hour', 3600],
    ['minute', 60],
  ]
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) {
      return formatter.format(Math.round(seconds / size), unit)
    }
  }
  return formatter.format(seconds, 'second')
}
