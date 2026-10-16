import { Search } from 'lucide-react'
import { useEffect, useState } from 'react'

export interface SearchFieldProps {
  /** The current value from the URL. Resets the local draft when it changes. */
  value: string
  onSearchChange: (value: string) => void
  /** Required, because "Find a model" is wrong on a page listing discussions. */
  label: string
  placeholder: string
  disabled?: boolean
}

/**
 * A debounced search box.
 *
 * Extracted from `GlobalFilters`, which hardcoded "Find a model" — and a label
 * that names the wrong thing is worse than no label, because it is the only
 * description of what the box searches. The props are required rather than
 * optional with a default, so every caller has to say what it searches.
 *
 * The debounce is why the component owns local state at all: typing has to feel
 * immediate while the URL — and therefore the request — updates 300 ms behind.
 * `key={value}` at the call site is *not* needed; the effect below re-syncs when
 * the URL changes underneath, which is what makes the browser's back button work.
 */
export function SearchField({
  value,
  onSearchChange,
  label,
  placeholder,
  disabled = false,
}: SearchFieldProps) {
  const [draft, setDraft] = useState(value)
  const [lastValue, setLastValue] = useState(value)

  // Re-sync when the URL changes underneath -- the back button, or a "clear
  // filters" button on another control. Adjusted **during render** rather than in
  // an effect: React's documented pattern for "state derived from a prop", and it
  // avoids the extra render pass an effect would cost on every navigation.
  if (value !== lastValue) {
    setLastValue(value)
    setDraft(value)
  }

  useEffect(() => {
    if (draft === value) return
    const timeout = window.setTimeout(() => onSearchChange(draft.trim()), 300)
    return () => window.clearTimeout(timeout)
  }, [draft, value, onSearchChange])

  return (
    <label className="filter-control filter-control--search">
      <span className="filter-control__label">{label}</span>
      <span className="filter-control__input-wrap">
        <Search aria-hidden="true" size={17} />
        <input
          disabled={disabled}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={placeholder}
          type="search"
          value={draft}
        />
      </span>
    </label>
  )
}
