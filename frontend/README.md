# LLM Picker frontend

React, TypeScript, and D3 frontend built with Vite.

## Quick Start

Prerequisites: Make sure you have `node.js` and `npm` installed.

```bash
# Install dependencies
npm install
# Start the development server
npm run dev
# Create the production build
npm run build
```

The development server runs on `http://localhost:5173` by default. The Django
backend permits local Vite ports while `DEBUG` is enabled.

## Routes

| Path | Page |
|---|---|
| `/` | Home |
| `/models` | Joined model table; `/models/:key` for one model |
| `/categories` | Task leaderboards, filtered by `?category=` |
| `/artificial-analysis` | The full AA catalogue |
| `/discussions` | LLM-related Hacker News threads |
| `/discussions/map` | **The discussion map**: threads, tree, reader |
| `/discussions/:hnId` | One thread, as an indented comment list |
| `/data-quality` | Matching and freshness |
| `/visualizations/*` | Performance vs cost, cost per task, task fit, model card |

`/discussions/map` is declared before `/discussions/:hnId` on purpose. React
Router ranks a static segment above a dynamic one so it resolves either way, but
if that ever changed, `map` would become a thread id and the page would 404 —
`src/App.test.tsx` pins it by asserting no `getDiscussion('map')` is ever issued.

### Discussions

A reader's view of the Hacker News bank: a searchable, filterable thread list, a
per-thread page that renders the comments as an **indented list**, and the map.

The indented list is deliberately not a tree — it is what makes the stored data
checkable by eye: the pre-order ordering, the sanitized markup, the per-comment
entity tags, and the truncation flag.

Two things worth knowing before editing these pages:

* **`text_html` is pre-sanitized** at ingest against an allowlist. It is the one
  place in this app that renders with `dangerouslySetInnerHTML`, and re-escaping it
  would show markup to the reader. Use `text_plain` for anything that is not HTML —
  a label, a tooltip, an `aria-label`.
* **`comments_stored` and `num_comments` are shown together**, because either alone
  misleads: the first is what we kept, the second is what Hacker News reports, and
  `tree_truncated` says whether the gap was the ingest cap.

Filter state lives in the URL (`q`, `entity`, `ordering`, `page`) via
`useDiscussionFilters`. It does **not** reuse the global filter band: that band's
`provider` parameter means an LMArena *organization string*, where this page's
filter means an entity *slug* — one key carrying two vocabularies is a
wrong-filter bug that presents as an empty result.

### The discussion map

ConVis's layout — threads on the left, the tree in the middle, the reader on the
right, search and filters on top — with four encodings: **indent is reply depth,
block height is post length, colour is the entity mentioned, and a yellow ring
means the post matches the search.**

A block carries no *comment* text — the map is an overview and the reader is where
reading happens — but it does name the entities it mentions, as a chip over the
fill. That is what makes the map readable without the legend, and it is the only
thing that names the entities past the end of the 14-hue palette, whose blocks
have no colour to carry them.

`discussionTree.ts` is the whole feature's brain and imports nothing: it builds
the tree from the flat comment array, decides what is collapsed, accumulates the
layout, and answers "which rows are in view". Everything decidable is decided
there and unit-tested; the components only paint what it returns.

Four things worth knowing before editing it:

* **The map is plain DOM, not SVG.** With no text in the blocks every mark is an
  axis-aligned rectangle, so the entity bands are a `linear-gradient`, the search
  ring is a `box-shadow`, and theming is a CSS variable the browser resolves
  itself — no `MutationObserver`, no redraw, unlike the scatter chart. It also
  makes each row a real `<button>`, so tab order and screen-reader labels are the
  platform's rather than a re-implementation.
* **Only the rows in view are in the DOM.** The largest stored thread draws a
  22,000px column; `windowRows` keeps that to ~24 rows at a time, which is why
  there is no virtualization dependency.
* **Height is a clamped power law, not proportional.** Comment length spans 30×
  (p50 191 characters, max 5,738), so linear makes one pasted log file own the
  pane and logarithmic flattens the body into indistinguishability. The clamp
  bounds the largest block at 6.9× the smallest.
* **The detail request is unfiltered** — `getDiscussion(hnId, {})`. The endpoint's
  `?max_depth`, `?search` and `?entity` all *trim the comment array*, which would
  leave children whose parents are missing. The map's entire encoding is a
  comment's position in the thread, so a trimmed response does not degrade the
  picture, it destroys it. Filtering happens client-side, against the whole tree.
  `DiscussionMapPage.test.tsx` asserts the call shape so this cannot regress
  quietly.

Map state lives in the URL via `useDiscussionMapState` (`thread`, `comment`, `q`,
`entity`, `depth`, `hidequiet`). `thread` and `comment` **push** a history entry
because they are navigation — Back should undo a focus — where the rest replace,
so a keystroke in the search box does not fill the history.

## Tests

```bash
# Run Oxlint
npm run lint
# Run TypeScript type checking
npm run typecheck
# Run unit tests
npm run test
```

## API Client

The typed API surface is exported from `src/api`. It uses
`http://127.0.0.1:8000/api/v1/leaderboard/` by default. Override the base URL in
a local `.env` file when needed:

```dotenv
VITE_API_BASE_URL=https://example.com/api/v1/leaderboard/
```
