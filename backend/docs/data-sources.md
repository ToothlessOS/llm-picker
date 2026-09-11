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

`slug` is unique across all 646 records, but **`id` (a UUID) is the upsert key**
— a slug rename must update the existing row, not create a second one beside it.

| Source path | Column | Type rule |
|---|---|---|
| `id` | `LLMModel.aa_id` | unique; the identity |
| `slug` | `LLMModel.slug` | unique |
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
intersection.** The normalizer recovers it: 12/38 `document`, 2/34 `search` and
35/127 `webdev` models are reachable from the `agent` set.

`search` intersecting to 2 and `document` to 12 is **inherent to the source, not
a defect**: search-specialized models (`gpt-5-search`,
`claude-opus-4-6-search`) genuinely do not exist in the `agent` split.

### Duplicate rows — `webdev` repeats models

`webdev` is **535 rows but only 127 distinct models** — each repeated up to 9×
with *inconsistent ranks* (`claude-opus-5-max` appears at ranks 3, 1, 3, 2, 3).
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

## 4. The only inference: the harness fold

One exception exists, and it is tightly bounded.

Some LMArena rows name a model *wrapped in an evaluation harness* rather than a
different model — `gpt-5.6-sol-xhigh (codex-harness)` is `GPT 5.6 Sol (xHigh)`
measured through Codex. The fold strips **one whole trailing token** from a
deliberately tiny, evidence-based list. `codex-harness` is the only entry, being
the only one observed in the real data.

It fires only when it yields **exactly one** candidate, and it is **guarded by a
sibling check**: if the fold's target base has more-specific variants present in
the index, it refuses rather than guessing. It correctly recovers 6 real webdev
models. Every fold match is recorded with its target and the stripped token, so
the whole inferred class is auditable and promotable to explicit aliases. Behind
`LEADERBOARD_ENABLE_HARNESS_FOLD` (default on).

### Rejected: folding reasoning effort

An earlier design also folded reasoning-effort tokens (`xhigh`/`high`/`max`/…).
Simulating it against real data produced **exactly one match and that match was
wrong** — `gpt-5.5-high` → `"GPT 5.5"`, when `"GPT 5.5 (xHigh)"` is the true
sibling — and **zero correct ones**. Reasoning effort is part of a model's
identity, not a wrapper around it. The fold is gone, and a regression test pins
that it stays gone.

Nothing is lost by this: AA and LMArena already use the *same* effort tokens
(`(xhigh)` ↔ `(xHigh)`), so they align exactly without folding. The models where
they do not agree — e.g. `Claude Fable 5.1 (Max)`, where AA publishes only
base/`low`/`medium` — stay **unmatched by design**. Inheriting a different
effort level's numbers would be actively misleading; a visible gap is not.

---

## 5. Licenses and attribution

| Source | Terms |
|---|---|
| Artificial Analysis | API v2, free tier. **A visible credit is required wherever their data is displayed.** |
| LMArena | `lmarena-ai/leaderboard-dataset` on Hugging Face, fetched via `datasets`. |

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
