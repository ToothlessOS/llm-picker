export type QueryPrimitive = boolean | number | string
export type QueryValue =
  | QueryPrimitive
  | readonly QueryPrimitive[]
  | null
  | undefined
export type QueryParams = Readonly<Record<string, QueryValue>>

function serializePrimitive(value: QueryPrimitive): string {
  if (typeof value === 'number' && !Number.isFinite(value)) {
    throw new TypeError(`Query parameter numbers must be finite, got ${value}.`)
  }

  return typeof value === 'string' ? value.trim() : String(value)
}

export function buildQueryString(query: QueryParams = {}): string {
  const searchParams = new URLSearchParams()

  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue

    if (Array.isArray(value)) {
      if (value.length === 0) continue
      searchParams.set(key, value.map(serializePrimitive).join(','))
      continue
    }

    const serialized = serializePrimitive(value as QueryPrimitive)
    if (serialized === '') continue
    searchParams.set(key, serialized)
  }

  return searchParams.toString()
}

export function commaSeparated<T extends string>(
  values: readonly T[] | undefined,
): string | undefined {
  return values?.length ? values.join(',') : undefined
}
