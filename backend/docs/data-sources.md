# Data sources — provenance and normalization

Where every stored value comes from, and every rule we apply to it on the way in.

The governing constraint: **field names are inspected, never assumed.** Both
sources are undocumented in the places that matter (LMArena's dataset has no
stable model id and no published schema; AA's reasoning-level convention is
inconsistent), so every claim below was verified against a real payload rather
than a spec.

---

## 1. Artificial Analysis — API v2

**Endpoint:** `GET /api/v2/language/models/free`
**Auth:** `x-api-key` header, from the `AA_API_KEY` environment variable.
**Pagination:** `?page=N` only, `page_size: 200`, loop while `has_more` is true,
with a hard `max_pages=8` guard (an upstream bug reporting `has_more: true`
forever must not burn the quota in a tight loop).
**Live volume:** 646 models across **4** pages (not the 2 a reading of their
example implies).

### Quota — read this before running anything

**100 requests per 24 hours, shared across every key in the organization.** A
full refresh costs **4**. Steady state is **8/day** (two refreshes), leaving the
rest for manual runs. The last-known state is echoed on every response and
persisted to `SyncRun`:

```
X-RateLimit-Limit / X-RateLimit-Remaining / X-RateLimit-Reset
X-AA-Tier
```

Rules built on that:

* **429 with `Retry-After` ≤ 60 s** → sleep and retry inline.
* **429 with a longer `Retry-After`** → do **not** sleep; fail the run with
  `error_code: rate_limit_exceeded`. Sleeping ~20 h inside a Celery worker is
  strictly worse than an honest failure that the next scheduled run recovers
  from.
* **Preflight**: if the last-known quota is exhausted, skip the run entirely and
  make zero HTTP calls.
* 401 / other 4xx → permanent failure, no retry storm. 5xx / timeouts /
  connection errors → exponential backoff (base 1 s, cap 30 s, jitter, max 4
  attempts).

### Field mapping

`slug` is unique **within any one snapshot** (verified: zero duplicates across the
699 records of the 2026-10-13 read), but it is **not stable per model** — AA
rotates a slug from one `id` to another across releases. See *Slug ownership*
below. **`id` (a UUID) is the upsert key**: a slug rename must update the existing
row, not create a second one beside it.

| Source path | Column | Type rule |
|---|---|---|
| `id` | `LLMModel.aa_id` | unique; the identity |
| `slug` | `LLMModel.slug` | unique per snapshot; reassignable across snapshots |
| `name` | `LLMModel.name` | verbatim; **the preferred match key** |
| `model_creator.id` / `.name` | `ModelCreator` FK (`PROTECT`) | upserted by UUID |
| `release_date` | `release_date` | date |
| *(response-level)* | `intelligence_index_version` | float; also on `SyncRun` |
| `evaluations.artificial_analysis_intelligence_index` | `intelligence_index` | float |
| `evaluations.artificial_analysis_coding_index` | `coding_index` | float |
| `evaluations.artificial_analysis_agentic_index` | `agentic_index` | float |
| `artificial_analysis_intelligence_index_cost.total_cost` | `intelligence_index_total_cost` | **Decimal** |
| `artificial_analysis_intelligence_index_cost.cost_per_task.total_cost` | `cost_per_task` | **Decimal** |
| `pricing.price_1m_input_tokens` | `price_1m_input_tokens` | **Decimal** |
| `pricing.price_1m_output_tokens` | `price_1m_output_tokens` | **Decimal** |
| `pricing.price_1m_cache_hit_tokens` | `price_1m_cache_hit_tokens` | **Decimal** |
| `pricing.price_1m_cache_write_tokens` | `price_1m_cache_write_tokens` | **Decimal** |
| `performance.median_output_tokens_per_second` | `median_output_tokens_per_second` | float |
| `performance.median_time_to_first_token_seconds` | `median_time_to_first_token_seconds` | float |
| `performance.median_time_to_first_answer_token_seconds` | `median_time_to_first_answer_token_seconds` | float |
| `performance.median_end_to_end_response_time_seconds` | `median_end_to_end_response_time_seconds` | float |

**Money is `Decimal`; indices, latency and throughput are `FloatField`.** Money
accumulates in sums and must not drift; the others are measurements where float
is the right type.

**The whole payload is kept in `raw_payload`** (never exposed by the API) so a
schema change that loses a field can be diagnosed without re-fetching — which
matters at 100 requests/day.

**Upstream `null` → DB `NULL`, never `0`.** AA's spec is explicit that nulls
mean "not measured"; a zero would draw a real data point at the origin, reading
as "free" or "instant". Enforced at the type-conversion layer
(`validation.as_float` / `as_int`) and asserted end-to-end in the test suite.

#### Slug ownership — unique per snapshot, but it moves between `id`s

Uniqueness and stability are two different claims, and only the first is true.
Both facts have to hold at once for the write to be safe, and they stop holding
together exactly when AA reassigns a slug.

Because the write is keyed on `id` while `slug` carries its own UNIQUE
constraint, the row that used to own a slug and the row that is about to take it
can be written in either order, and only one of those orders is safe. This is not
hypothetical: it took the AA leg of the refresh down for every scheduled run from
2026-10-13.

| | `id` | `slug` | `name` |
|---|---|---|---|
| before | `901ec71b-…-b890b4` | `jt-4-1-flash-236b-a21b` | JT-4.1 Flash 236B A21B |
| after | `901ec71b-…-b890b4` | `jt-4-1-flash-236b-a21b-non-reasoning` | JT-4.1 Flash 236B A21B (Non-reasoning) |
| after | `46f11cdf-…-48149c` *(new)* | `jt-4-1-flash-236b-a21b` | JT-4.1 Flash 236B A21B (Reasoning) |

AA split one model in two and handed the bare slug to the new reasoning variant —
a release that changes two rows' slugs at once, in an order nothing controls.

Rule: **`persistence.release_claimed_slugs` vacates every slug the payload claims
for a different `id` before a single row is written**, inside the same
transaction as the upsert. After that pass no other row holds a claimed slug, so
every later write is free whatever the payload order. A row that is itself in the
payload has its real slug written moments later, so the released value is never
committed; a row that has dropped out of the catalogue keeps it, is deactivated,
and is reported as a `slug_reassigned` anomaly. A slug that used to address one
model now addressing another is worth a human look, but it is never a reason to
fail the run.

This is the AA-side counterpart of the `webdev` duplicate rule below: in both
cases a natural key that looks like an identity is not one, and the writer has to
reconcile it before the constraint can fire.

### Reasoning levels — the trap that shapes the matching

AA publishes **one row per reasoning level**, and where the effort marker lives
is inconsistent:

* baked into the slug — `gpt-5-6-luna-low`, `claude-fable-5-1-medium`,
  `qwen3-5-122b-a10b-non-reasoning` (49 of 200 rows on page 1);
* present **only in the name** — slug `gpt-5-5` → name `"GPT-5.5 (xhigh)"`,
  slug `gpt-6-astra` → name `"GPT-6 Astra (max)"`.

21 of ~200 base models on page 1 have more than one AA row. Both vocabularies do
overlap (`high`/`xhigh`/`max`/`medium`/`low`/`minimal`/`non-reasoning`), **but
AA's bare slug denotes a different reasoning level than its own name does**:

| AA slug | AA name | LMArena `agent` keys |
|---|---|---|
| `gpt-5-5` | `GPT-5.5 (xhigh)` | `gpt-5-5` (base), `gpt-5-5-xhigh` |
| `gpt-6-astra` | `GPT-6 Astra (max)` | `gpt-6-astra-max` |

Trying the slug first attaches the **xhigh** row to the **base** model. This is
why the ladder keys on the normalized `name` first and only falls back to the
slug when the name carries no effort marker — see [implementation.md](implementation.md).

---

## 2. LMArena — Hugging Face dataset

**Access:** `load_dataset("lmarena-ai/leaderboard-dataset", "<field>",
split="latest")`, imported **lazily inside the loader callable** so the DRF
process never pays `datasets`' import cost and no request can reach it.

**Fields loaded:** `agent`, `document`, `search`, `webdev`. The `full` splits are
never requested — there is no code path to them. This project stores the latest
state only; there is no history and no backfill.

**Retries:** once on network failure. A missing column fails that field with a
schema error. `agent` failing aborts the whole LMArena run (it anchors every
intersection); the other three failing individually yields `partial` — the
fields that loaded are still written.

### Field mapping

All four splits report `category == "overall"` upstream, and **none exposes a
stable model id** — `model_name` is the only identity, which is the single most
consequential fact about this source.

| Column (`agent` / others) | DB column | Notes |
|---|---|---|
| `model_name` | `model_name`, plus `model_key` | Verbatim display name; `model_key` is our normalized form of it. |
| `organization` | `organization` | |
| `license` | `license` | |
| `rank` | `rank` | Per-category, not global. |
| `score` / `rating` | `metric_value` | **Different scales** — see below. |
| `score_ci_lower` / `rating_lower` | `metric_lower` | |
| `score_ci_upper` / `rating_upper` | `metric_upper` | |
| — / `variance` | `metric_variance` | Rating categories only. |
| `observation_count` / `vote_count` | `sample_size` | Renamed to one neutral column. |
| `session_count` | `session_count` | `agent` only. |
| `leaderboard_publish_date` | `leaderboard_publish_date` | Date string upstream. |
| *(whole row)* | `source_metadata` | Never exposed by the API. |

### score vs rating — do not mix them

* `agent` publishes an Elo-style **`score`** (≈0.0–0.2 in current data).
* `document`/`search`/`webdev` publish Bradley-Terry **`rating`s** (≈1000–1600).

They are **not comparable**. `metric_kind` records which is which, travels with
every value into the API response, and the frontend must not plot them on one
axis.

### Two naming conventions that do not join

The `agent` split uses display names (`"Claude Opus 5 (High)"`, `"GPT 5.6 Sol
(xHigh)"`) while the other three use slugs (`claude-opus-5-high`,
`gpt-5.6-sol-xhigh`). **Exact string matching between them yields a zero
intersection.** The normalizer recovers it: 17/44 `document`, 2/34 `search` and
37/128 `webdev` models are reachable from the `agent` set.

`search` intersecting to 2 and `document` to 17 is **inherent to the source, not
a defect**: search-specialized models (`gpt-5-search`,
`claude-opus-4-6-search`) genuinely do not exist in the `agent` split.

### Duplicate rows — `webdev` repeats models

`webdev` repeats each model several times (at the 2026-09-11 sync, **535 raw rows
for 127 distinct models**, each repeated up to 9×) with *inconsistent ranks*
(`claude-opus-5-max` appears at ranks 3, 1, 3, 2, 3).
Dedupe by normalized key is mandatory, not a nicety: a naive unique constraint
would crash the refresh.

Rule: sort by `(rank is None, rank, model_name)` and keep the first per
normalized key. Losers are recorded as `duplicate_model_name` anomalies with
both ranks. This resolves the webdev collisions to the best rank and means the
`(category, model_key)` constraint can never fire.

**`entry_count` on `/categories/` is the deduplicated count.** The
`records_deduplicated` counter on `SyncRun` reports how many rows this collapsed.

---

## 3. The normalization rule

One function, used by every join, and it is the only comparison this project
performs:

```python
def normalize_model_key(value: str) -> str:
    # NFKC → casefold → every run of non-[a-z0-9] → "-" → trim "-"
```

Applied to `"Claude Opus 5 (High)"` → `claude-opus-5-high`, and to
`gpt-5.6-sol-xhigh` → `gpt-5-6-sol-xhigh`. It is idempotent, deterministic and
lossless with respect to variant suffixes — deliberately **preserving**
parentheticals, because `(High)` and `(xHigh)` are different models.

This is what makes the cross-category join possible at all, and it is why
nothing in this project needs fuzzy matching: after normalization the comparison
is still plain string equality.

**What is explicitly not done:** no similarity scoring, no Levenshtein, no
substring or prefix matching, no inference that two names "look like" the same
model. `gpt-5` must never match `gpt-5-mini`, `gpt-5.1-codex` or `gpt-4o`, and
the test suite asserts exactly that.

---

## 4. The two derived rungs

Two rungs derive the key they compare against. Both are tightly bounded, and
neither invents a candidate — each only **re-spells one a source already stated**.
Every match either produces is recorded with the rung that produced it, so the
whole class is auditable and promotable to explicit aliases.

### The harness fold

Some LMArena rows name a model *wrapped in an evaluation harness* rather than a
different model — `gpt-5.6-sol-xhigh (codex-harness)` is `GPT 5.6 Sol (xHigh)`
measured through Codex. The fold strips **one whole trailing token** from a
deliberately tiny, evidence-based list. `codex-harness` is the only entry, being
the only one observed in the real data.

It fires only when it yields **exactly one** candidate, and it is **guarded by a
sibling check**: if the fold's target base has more-specific variants present in
the index, it refuses rather than guessing. It correctly recovers 6 real webdev
models. Every fold match is recorded with its target and the stripped token.
Behind `LEADERBOARD_ENABLE_HARNESS_FOLD` (default on). This is the only rung that
is genuinely an *inference*, and the only one whose matches carry
`confidence < 1.0`.

### The stated-effort rung — `exact_effort_slug`

AA states a reasoning level in `name` and publishes that variant under a slug that
does not carry it, while LMArena keys it with a suffix:

| AA slug | AA name | LMArena agent key |
|---|---|---|
| `claude-opus-5` | `Claude Opus 5 (Adaptive Reasoning, Max Effort)` | `claude-opus-5-max` |

`has_effort_marker` cannot see that prose (the name ends in `effort`, not an
effort word), so the name rung misses and the slug rung tries the bare
`claude-opus-5`, which LMArena does not publish. `effort_from_name` reads the
level **AA explicitly states** and the rung appends it.

This is not the rejected effort fold in disguise, and the distinction is the whole
reason it is safe. The fold *removed* a token and could therefore land on a
different level; this rung *adds* the level the source itself named, producing a
key strictly **more specific** than the record's slug. It is structurally unable
to reach across effort levels, which is also why it needs none of the fold's
sibling shadowing check. It requires the word `Effort` to be present — a bare
`(Adaptive Reasoning, Max)` mid-name states nothing and is refused.

### AA's fallback annotation is not identity

AA appends a routing annotation as the last clause of the effort parenthetical:

| AA name | LMArena agent name |
|---|---|
| `Claude Opus 5.5 (Max, Default Fallback)` | `Claude Opus 5.5 (Max)` |
| `Claude Fable 5 (Max, Opus 4.8 Fallback)` | — (LMArena has Fable 5 at High) |

The clause says which model backs the row up; it is **provenance, not identity**,
and LMArena names the same row without it. `strip_fallback_annotation` removes
one such trailing clause **before** the name is normalized. It is deliberately
narrow — only the final parenthetical, one comma-separated clause, ending in the
word `Fallback`, no nested parentheses — and it is never applied to slugs,
LMArena names, or the stored `LLMModel.name`.

Two things follow, both wanted:

* the exact-name rung can now resolve `claude-opus-5-5-max`; and
* `has_effort_marker` sees the stated `Max`, so the bare-slug rung is **closed**.
  Before the cleanup the annotation hid the effort, leaving AA's Max record free
  to fall through to a bare `claude-opus-5-5` key — the same wrong-level trap the
  rung order exists to prevent.

Aliases and the unmatched ledger stay keyed on the verbatim upstream spelling, so
a reviewer still copies exactly what the report shows.

### Rejected: folding reasoning effort

An earlier design also folded reasoning-effort tokens (`xhigh`/`high`/`max`/…).
Simulating it against real data produced **exactly one match and that match was
wrong** — `gpt-5.5-high` → `"GPT 5.5"`, when `"GPT 5.5 (xHigh)"` is the true
sibling — and **zero correct ones**. Reasoning effort is part of a model's
identity, not a wrapper around it. The fold is gone, and a regression test pins
that it stays gone.

The models where the two sources genuinely **disagree** about the level stay
**unmatched by design**. `Claude Fable 5 (High)` is the example: AA publishes
Fable 5 at Max Effort only, so the High row has no counterpart and inheriting the
Max numbers would be actively misleading. A visible gap is not. What the
stated-effort rung fixes is the narrower case where the sources *agree* and only
our reading of AA's prose was failing.

---

## 5. Licenses and attribution

| Source | Terms |
|---|---|
| Artificial Analysis | API v2, free tier. **A visible credit is required wherever their data is displayed.** |
| LMArena | `lmarena-ai/leaderboard-dataset` on Hugging Face, fetched via `datasets`. |
| Hacker News | Algolia's public search API. No licence or credit obligation, but every served thread and comment carries its `hn_url`, so a reader can always reach the original discussion. |

The required attribution URLs are served by the API in `/metadata/`'s top-level
`attribution` block, so the frontend reads them rather than hard-coding them.
That block is on `/metadata/` only — the pagination `meta` envelope carries
`generated_at` and freshness, not attribution. Render the credit wherever AA
metrics appear.

---

## 6. What is deliberately not stored

| Not stored | Why |
|---|---|
| Historical snapshots / time series | Latest-only. The `full` splits are unused; there is no backfill. |
| Pairwise battle counts | The proposal's battle-count heatmap needs comparison counts the leaderboard dataset does not publish. Out of scope. |
| `raw_payload` / `source_metadata` exposure | Kept for troubleshooting, never returned by the API — the API serves normalized fields only, so an upstream schema change is a backend concern rather than a breaking change for the frontend. |
| A Hacker News thread's full comment tree as JSON | The comments are rows, because keyword search has to reach comment text and a blob cannot answer that on SQLite. The thread's `raw_payload` keeps the story's own fields plus the key-set observed on comment nodes — what actually diagnoses drift — rather than duplicating megabytes of the same text. |
| Unfetched Hacker News comments | The busiest threads run past 2,500 comments, so a tree is capped at `LEADERBOARD_HN_MAX_STORED_COMMENTS`. The thread records `tree_truncated` and both counts, so the shortfall is visible rather than looking like a quiet discussion. |

---

## 7. Hacker News — Algolia search API

**Endpoints:** `GET https://hn.algolia.com/api/v1/search_by_date` for discovery,
`GET https://hn.algolia.com/api/v1/items/{id}` for a comment tree.
**Auth:** none. The API is open, so there is no key to configure, no `configured:
false` state, and nothing here is a secret.

### Why the official Firebase API is not used

The feature draft named both APIs. Only Algolia is implemented, and the arithmetic
is the reason:

| Operation | Firebase | Algolia |
|---|---|---|
| Find candidates filtered by points/comments/date | none — `topstories.json` returns 500 ids with no metadata, so filtering means fetching 500 items to look at them | 1 request; `numericFilters` does it server-side |
| Full tree for a 360-comment thread | ~361 requests (one per comment) | **1** |
| Hourly cost for this design | ~3,600+/hour | ~65–80/hour |

Neither API needs a key, so Firebase offers no auth advantage. A second source
would buy a second error taxonomy, a second test fake, a second schema-drift
surface, and an arbitration rule for "which source wins" — which `SyncRun`'s
per-source partial unique index actively discourages. One source, one client, one
set of rules.

### Two properties that fail *silently*

**The 1,000-result ceiling.** `hitsPerPage * page` cannot exceed 1,000, and past
it the API returns a *plausible-looking truncated set* rather than an error. A
single query covering the whole retention window would therefore lose its oldest
days while looking complete. Two guards: the window is queried in
`LEADERBOARD_HN_WINDOW_SLICE_DAYS` slices (7 days by default, so a fortnight is
two queries, newest first), and the client refuses a page beyond the ceiling
rather than reading one. `nbHits` is compared against what was actually collected,
and the difference is reported as `window_truncated`.

**Enormous payloads.** A thousand-comment thread is megabytes of JSON, so
`Content-Length` is checked *before* the body is read. A chunked response has no
such header, which is why there are two further guards rather than one: a
pre-flight refusal above `LEADERBOARD_HN_MAX_COMMENTS` (which spends no request at
all), and an ingest cap of `LEADERBOARD_HN_MAX_STORED_COMMENTS` on what is kept.

The **stored cap** is the one that binds, and the gap up to the refusal is not
slack -- it is the widest discussion that can be shown at all. A thread above the
refusal keeps no comments and is skipped by every run, so it presents exactly like
one whose tree has not been fetched yet: a real limitation, visible in the UI, and
the reason the two numbers are documented together.
Truncation is recorded as `tree_truncated` on the thread, because a silently
short discussion reads as a complete one.

That refusal is deliberately generous (3,000). It guards download size only —
storage is already bounded by the stored cap — and the busiest threads on the site
routinely pass 1,500 comments, so a tight refusal would drop exactly the
discussions most worth reading.

### Discovery, in two streams

**The window query** is the primary source of truth: `search_by_date` with
`numericFilters` on `created_at_i`, `points` and `num_comments`, so the floor is
applied by the server. Because `search_by_date` orders by recency, ranking is
computed **locally** afterwards.

**A budgeted keyword sweep** is the coverage hedge: at most
`LEADERBOARD_HN_KEYWORD_QUERY_BUDGET` queries per run, walked round-robin over a
priority term list, catching a genuinely relevant thread that sits below the
points floor.

The sweep has its **own, lower** floor (`LEADERBOARD_HN_SWEEP_MIN_*`, 30 points /
5 comments). That is not a refinement but a correction found on live data: with no
floor at all, the sweep dragged in 556 of the first 633 stored threads at under 20
comments, some with two points, because a date bound is not a relevance bar. The
two floors answer different questions -- the window's is "is this one of the
notable stories of the period?", the sweep's is "is this a real discussion rather
than trivia?" -- and reusing the window's would make the sweep unable to find
anything the window had not already found. The cursor lives in the previous successful run's `SyncRun.summary`
— it is a *position*, not a fact, so losing it costs one repeated sweep rather than
any correctness. Round-robin rather than sweeping everything keeps the hourly cost
constant however large the vocabulary grows.

Relevance is decided on the **title and link domain only**, never the comment
bodies: it is settled at discovery time, before any tree has been fetched, and a
story that only becomes about LLMs three hundred comments deep is not what "an
LLM-related thread" means. The terms that fired are stored on the thread, so "why
is this in the bank?" is answerable from the row.

### Retention — the one place this project DELETEs

Every other source here records measurements the project owns, so a row that
vanishes upstream is deactivated and **never** deleted: our copy is the last one,
and the previous state has to stay inspectable.

A Hacker News thread is the opposite. `GET /items/{id}` keeps serving it forever,
so an aged-out row is a **re-fetchable cache entry** rather than the last copy of a
measurement. A thread leaves the bank in one of two ways, and both are the same question --
"is this still something we keep?":

* **Too old** — posted before `LEADERBOARD_HN_WINDOW_DAYS` (14).
* **Below the floor** — under `LEADERBOARD_HN_SWEEP_MIN_POINTS` /
  `LEADERBOARD_HN_SWEEP_MIN_COMMENTS`, or with a comment count Hacker News does
  not report. Applying the floor here and not only at discovery is what keeps the
  floors *the retention policy* rather than a rule consulted once: an operator who
  raises them sees the bank follow, and the run reports how much moved under
  `threads_below_floor`.

The floor applied is the **sweep's**, deliberately, not the window's. Raising the
window floor is a discovery decision and should change what is *found*, not
silently empty what is already stored.

Either way the thread is deleted outright, with its comments and tags, in the same
transaction as the run's writes — which also means a `--dry-run` rolls the prune back with everything
else, so the effect of a window change can be inspected before it deletes
anything. Recovery from a mistake is one `manage.py refresh_discussions` run.

The safety this buys is worth stating: age-based pruning makes membership
**monotonic**. `posted_at` is immutable and the cutoff only moves forward, so
nothing can re-enter the bank. That single property removes the need for an
`is_active` flag, for a miss-counter suppressing hysteresis at a rank boundary, and
for a stored `is_top` — ranking is a plain `ORDER BY`, and the table's contents
*are* the served set.

### Matching prose to entities

§3 forbids similarity scoring, Levenshtein, substring and prefix matching, and the
tests enforce it. Matching Hacker News prose against a vocabulary sounds like the
thing that rule forbids, so the resolution is a **scoping argument backed by exact
mechanics**:

> §3 compares *two records the sources state*. This compares *a string against a
> table a human wrote*, producing advisory tags on discussion content. It never
> produces a `ModelMatch`, never influences `/overview/`, `/models/{key}/` or
> `/unmatched/`, and never feeds the ladder. No scoring exists in either.

Three modes, all exact, all in `hn_matching.py`:

| Mode | Rule | Fires | Refuses |
|---|---|---|---|
| `word` | the alias equals one whole word | `openai` on "OpenAI's API" | `openai-compatible` |
| `token_run` | the alias's tokens equal a whole hyphen-joined token run | `gpt-5` on "GPT-5" | "GPT-5-mini" |
| `token_prefix` | the alias's tokens lead one word, optionally followed by a version number | `gpt` on "GPT-5" and "GPT4"; `qwen` on "Qwen3" | `rag` on "rage"; `phi` on "philosophy" |

`token_prefix` is what keeps the vocabulary a list of *subjects* rather than an
enumeration of versions that goes stale on every release. It is a **token**-level
prefix and never a character-level one — any flush remainder must begin with a
digit — which is what makes writing a vendor stem down safe. It is for vendor and
service stems, not model variants: marking `gpt-5` as a prefix is how "GPT-5-mini"
would wrongly inherit GPT-5's identity, and that stays a rule a reviewer keeps,
because the mode is per-alias and visible in the admin.

The escape hatch for everything the rules refuse is a reviewed alias in
`ProviderAlias`, seeded from `hn_vocabulary.py` by migration `0009` and editable in
the admin. `alias_key` is **globally unique**, so two entities cannot both claim
"claude": the database refuses the insert rather than the matcher picking a winner.

### What a tag is, and when it is rebuilt

A tag is a stored row, not an inference — matching runs at ingest, which is what
lets the API's filter be a join and keeps the read path unable to reach the
network. Two consequences follow, and both are deliberate:

* **Title tags are rebuilt on every run.** One matcher call per thread, and
  skipping it would leave a thread whose tree was deferred this hour with no tags
  at all — not even the one its own title earned.
* **Comment tags are rebuilt only when the tree was refetched.** The alternative
  is loading a few hundred thousand comment rows into memory every hour to redo
  work that has not changed. So a change to a *comment* alias reaches an existing
  thread through `manage.py refresh_discussions --skip-discovery`, which forces the
  refetch, or automatically once that thread's comment count moves. Deleting a
  `ProviderEntity` cascades its tags away by the same route.
