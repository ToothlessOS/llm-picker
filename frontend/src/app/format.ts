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
