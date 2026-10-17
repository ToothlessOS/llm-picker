import { useQuery } from '@tanstack/react-query'

import { getMetadata } from '../../api'
import { formatNumber } from '../../app/format'

/**
 * Live counts for the home community card.
 *
 * The drawing itself is a static illustration. A real map thumbnail would fetch
 * a thread's comment tree — up to a megabyte — for a small card. These counts
 * come from the `meta` block `AppShell` already polls, so the card still reports
 * live numbers without an extra request.
 */
export function DiscussionMapPreview() {
  const metadata = useQuery({
    queryKey: ['metadata'],
    queryFn: ({ signal }) => getMetadata({ signal }),
    refetchInterval: 60_000,
  })

  const counts = metadata.data?.discussions?.counts

  return (
    <p className="home-community__counts">
      {counts
        ? `${formatNumber(counts.threads, 0)} threads · ${formatNumber(
            counts.comments,
            0,
          )} comments · ${formatNumber(counts.entities, 0)} providers and services`
        : 'LLM discussions from Hacker News'}
    </p>
  )
}
