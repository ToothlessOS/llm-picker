# Leaderboard API — frontend reference

Read-only HTTP API over two upstream sources: **LMArena** (the Hugging Face
`lmarena-ai/leaderboard-dataset`) and **Artificial Analysis** (API v2).

**Base path:** `/api/v1/leaderboard/`

```
GET /api/v1/leaderboard/overview/
GET /api/v1/leaderboard/categories/
GET /api/v1/leaderboard/categories/{category}/
GET /api/v1/leaderboard/artificial-analysis/
GET /api/v1/leaderboard/models/{key}/
GET /api/v1/leaderboard/metadata/
GET /api/v1/leaderboard/unmatched/
```

Every endpoint is `GET` only (plus `HEAD`/`OPTIONS`); anything else is a `405`
with the standard error body. There is no authentication and no write path.

**No request of yours triggers an upstream call.** All data is ingested by a
scheduled job twice a day and served from the database. Response time does not
depend on LMArena's or Artificial Analysis's availability, and neither does
yours.

The version lives in the path, so a breaking change can ship as `/api/v2/`
while v1 keeps working.

---

## ⚠️ Start here: the completeness rule

This governs what you may assume about every row, so it comes before the
endpoint list.

**`/overview/` and `/models/{key}/` serve *complete* entries only.** An entry is
complete when it has **both** an LMArena `agent` row **and** a matched
Artificial Analysis record. Everything on those two endpoints therefore has
`model`, `categories.agent`, `aa` and `match` populated — you never need to
guard against a half-populated row there, and you should not write `?.` chains
or "—" fallbacks for the joined fields.

Two things this does **not** mean, both important:

1. **A missing *category* is not incompleteness.** A model that was never
   evaluated in `document` or `search` still counts as complete and is served
   with that block as an explicit `null`. Absence of a category is real
   information — the model was not tested there. Render the null as "not
   evaluated"; do not treat it as missing data.
2. **A `null` *metric* is not incompleteness either.** The AA spec uses `null`
   for "not measured", and we preserve that faithfully. A `null` cost is
   "unmeasured", **never zero**. Plotting it as `0` draws a real point at the
   origin that reads as "this model is free".

**Which endpoints guarantee what:**

| Endpoint | Guarantee |
|---|---|
| `/overview/` | Complete entries only. Every row has an AA match. |
| `/models/{key}/` | Same rule. A real-but-unmatched model is a `404 model_incomplete`. |
| `/categories/{category}/` | **Single-source, unfiltered.** May contain rows with no AA match. |
| `/artificial-analysis/` | **Single-source, unfiltered.** May contain rows with no LMArena presence. |
| `/unmatched/` | Every row the joined endpoints drop, with a reason. |

So the joined surface is intentionally the *smallest* of the three. On live data
(2026-09-11) that is **30 complete entries** out of 43 agent models — see
[coverage](#coverage-what-is-and-is-not-joined) for why, and for how a gap gets
fixed.

### The `404 model_incomplete` is a normal state, not an error

`GET /models/{key}/` for a model excluded by the rule is a `404` — deliberately,
so a dead link explains itself instead of rendering half-empty. **Do not treat
this as an error to escalate or retry.** It carries `reason`, a human-readable
`message`, and a `detail` block naming where the model *is* available:

```json
{
  "error": "model_incomplete",
  "model_key": "gpt-5-5-xhigh",
  "reason": "no_aa_match",
  "message": "'GPT 5.5 (xHigh)' is in LMArena's `agent` split, but no Artificial Analysis record resolved to it at the same reasoning level. It is therefore not served by the joined endpoints. It remains available through /categories/agent/ and /unmatched/; a `ModelAlias` is the way to join it.",
  "detail": {
    "model_name": "GPT 5.5 (xHigh)",
    "rank": 2,
    "agent_key": "gpt-5-5-xhigh",
    "unmatched": {
      "source": "lmarena",
      "category": "agent",
      "reason": "no_aa_match",
      "detail": {"rank": 2, "aa_records_considered": 646},
      "last_seen_at": "2026-09-11T10:52:52.648025Z"
    }
  }
}
```

Suggested frontend behaviour: render the message, link to
`/categories/agent/` filtered to that key. Never a generic "something went
wrong".

---

## The three calls a dashboard actually needs

**1. Build the page, with a freshness badge** — one request gives you rows *and*
the "data as of …" timestamp:

```js
const res = await fetch('/api/v1/leaderboard/overview/?ordering=-aa_intelligence_index&page_size=50');
const { results, count, next, meta } = await res.json();

meta.generated_at                   // "2026-09-11T10:52:52Z" — when this response was built
meta.sources.artificial_analysis    // { last_success_at, is_stale, age_seconds, ... }
meta.sources.lmarena
```

The badge and the rows come from the same request, so they cannot disagree.

**2. Render one row's detail** — the category blocks are already on the row, so
the detail page needs no second call unless you want the full AA metric set:

```js
const r = results[0];
r.categories.agent.metric_value   // 0.114   (kind: "score")
r.categories.webdev.rank          // 7
r.categories.search               // null — never evaluated in `search`
r.aa.intelligence_index           // 62.5    (null if unmeasured)
r.aa.pricing.price_1m_input_tokens
```

**3. Show the review queue** — the models `/overview/` excludes:

```js
const q = await (await fetch('/api/v1/leaderboard/unmatched/?reason=no_aa_match')).json();
// q.count, q.results[].model_name — the models to sanity-check against AA's site
```

---

## Conventions

### Pagination

Every endpoint except `/categories/` and `/metadata/` is paginated at **50 per
page** (`page_size`, max **200**; larger values are *clamped* and the effective
value is echoed back, so always read `page_size` from the response).

```json
{
  "count": 30,
  "next": "http://localhost:8000/api/v1/leaderboard/overview/?page=2&page_size=1",
  "previous": null,
  "page_size": 1,
  "results": [ ... ],
  "meta": { ... }
}
```

* `page` out of range → `404` (DRF's standard behaviour, kept so you see one
  shape everywhere).
* `page_size=abc` → `400 invalid_parameter` — a silent fallback would answer a
  different question than you asked.
* Each endpoint's `meta` carries `generated_at` and the per-source freshness
  block, plus any endpoint-specific keys (`categories_included`, `metric_kind`,
  …).

### Rate limits

Every endpoint is limited per client IP, and a request must satisfy **both**
budgets:

| Scope | Default | Env var |
|---|---|---|
| Burst | 60 requests / minute | `LEADERBOARD_THROTTLE_BURST` |
| Sustained | 2000 requests / day | `LEADERBOARD_THROTTLE_SUSTAINED` |

Both counters are per IP, so one client cannot spend another's budget. Exceeding
either returns `429` — see [Errors](#errors) — with a `Retry-After` header giving
the whole seconds to wait. A page load that fetches a handful of endpoints is far
inside both budgets; a polling loop will meet the burst limit first.

What costs nothing: **CORS preflights**. An `OPTIONS` carrying
`Access-Control-Request-Method` is answered by the CORS middleware before any
view runs, so it is never counted. Everything else the server routes is counted —
including a bare `OPTIONS` without that header, and `HEAD`, which both reach the
view. A monitor polling with `HEAD` therefore spends the budget like any other
caller. (`/admin/` is session-authenticated and entirely outside this limiter.)

### Field origin markers

Every field below is tagged, so you know which side of the join you are reading
and what can change without warning:

| Marker | Meaning |
|---|---|
| `source-confirmed` | Comes from the upstream payload, under the name the source publishes (or a documented rename). We do not invent these values. |
| `backend-derived` | Computed by this backend — the normalized join key, the match record, freshness, retention. Our definition, documented here. |

### Ordering

`?ordering=field` or `?ordering=-field` for descending; comma-separate for
ties. **All orderings put nulls last** — the sources publish `null` for "not
measured", and SQLite's default would otherwise float every unmeasured model to
the top of your chart. A `pk` tiebreak is appended unconditionally, so rows tied
on the ordered field never shuffle between pages.

An unknown ordering key is a `400` with `allowed` listing every valid key —
never a silent fallback.

### Timestamps

Always ISO-8601, always UTC, always `Z`-suffixed. Dates that are genuinely dates
(`release_date`, `leaderboard_publish_date`) are `YYYY-MM-DD` with no time.

### Money and units

Money (`cost_per_task`, `intelligence_index_total_cost`,
`price_1m_*_tokens`) is serialized as a **JSON number**, not a string, so you can
format it directly. Decoded from `Decimal` at the DB layer, so sums do not
drift.

---

## 1. `GET /overview/` — joined list

The visualization-ready surface. **Complete entries only.**

`model.key` is the identity you should use for `/models/{key}/` links.

### Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `search` | string | — | Case-insensitive substring of `model_name` **or** `organization`. |
| `organization` | string | — | Exact, case-insensitive. |
| `rank_min` / `rank_max` | int | — | On the `agent` rank. |
| `metric_min` / `metric_max` | number | — | On the `agent` metric value. |
| `sample_min` / `sample_max` | int ≥ 0 | — | On the `agent` sample size. |
| `include_categories` | csv | all three | Any of `document,search,webdev`. Also accepts `all`, `none`. Filters which blocks are *populated*: the four keys are always present on every row, with the unwanted ones `null` (and `agent` is never null here). Use it to keep list payloads small when a view does not show every category. |
| `ordering` | csv | `rank` | See keys below. |
| `page`, `page_size` | int | 1, 50 | |

**Ordering keys:** `rank`, `model_name`, `organization`, `metric_value`,
`sample_size`, `session_count`, `leaderboard_publish_date`, and any `aa_`-prefixed
AA metric (`aa_intelligence_index`, `aa_cost_per_task`,
`aa_price_1m_input_tokens`, `aa_intelligence_index_total_cost`,
`aa_coding_index`, `aa_agentic_index`, `aa_price_1m_output_tokens`,
`aa_price_1m_cache_hit_tokens`, `aa_price_1m_cache_write_tokens`,
`aa_median_output_tokens_per_second`,
`aa_median_time_to_first_token_seconds`,
`aa_median_time_to_first_answer_token_seconds`,
`aa_median_end_to_end_response_time_seconds`).

There is deliberately **no** `matched` or `has_aa` parameter here: both are
invariantly true. For the excluded rows use `/categories/{category}/`,
`/artificial-analysis/` or `/unmatched/`.

### Response

```json
{
  "count": 30,
  "next": null,
  "previous": null,
  "page_size": 50,
  "results": [
    {
      "model": {
        "key": "claude-opus-5-high",
        "name": "Claude Opus 5 (High)",
        "organization": "anthropic",
        "license": "Proprietary",
        "in_agent_set": true
      },
      "categories": {
        "agent": {
          "category": "agent",
          "metric_kind": "score",
          "metric_value": 0.114,
          "metric_lower": 0.096,
          "metric_upper": 0.131,
          "metric_variance": null,
          "sample_size": 2794373,
          "session_count": 23232,
          "rank": 1,
          "model_name": "Claude Opus 5 (High)",
          "organization": "anthropic",
          "license": "Proprietary",
          "leaderboard_publish_date": "2026-09-08",
          "source_key": "claude-opus-5-high",
          "matched_by_fold": false
        },
        "document": { "...": "same shape, metric_kind: \"rating\"" },
        "search": null,
        "webdev": { "...": "same shape, metric_kind: \"rating\"" }
      },
      "aa": {
        "id": "uuid-claude",
        "slug": "claude-opus-5-high",
        "name": "Claude Opus 5 (High)",
        "creator": {"id": "creator-anthropic", "name": "Anthropic"},
        "release_date": "2026-05-04",
        "intelligence_index_version": 4.3,
        "intelligence_index": 62.5,
        "coding_index": null,
        "agentic_index": null,
        "intelligence_index_total_cost": 59.99,
        "cost_per_task": 0.0502,
        "pricing": {
          "price_1m_input_tokens": 15.0,
          "price_1m_output_tokens": null,
          "price_1m_cache_hit_tokens": null,
          "price_1m_cache_write_tokens": null
        },
        "performance": {
          "median_output_tokens_per_second": null,
          "median_time_to_first_token_seconds": null,
          "median_time_to_first_answer_token_seconds": null,
          "median_end_to_end_response_time_seconds": null
        },
        "is_retained": true,
        "last_synced_at": "2026-09-11T10:52:52.648025Z"
      },
      "match": {
        "method": "exact_name",
        "confidence": 1.0,
        "is_manual": false,
        "matched_key": "claude-opus-5-high",
        "last_matched_at": "2026-09-11T10:52:52.648025Z"
      }
    }
  ],
  "meta": {
    "generated_at": "2026-09-11T10:52:52.700000Z",
    "sources": { "...": "see /metadata/" },
    "categories_included": ["document", "search", "webdev"]
  }
}
```

### Field reference

**`model`**

| Field | Origin | Notes |
|---|---|---|
| `key` | backend-derived | Normalized join key. Use it for `/models/{key}/`. Stable while the upstream name is. |
| `name` | source-confirmed | LMArena `agent` `model_name`, verbatim. |
| `organization` | source-confirmed | Verbatim. |
| `license` | source-confirmed | Verbatim, e.g. `Proprietary`, `Apache 2.0`. |
| `in_agent_set` | backend-derived | Always `true` on this endpoint. |

**`categories.{category}`** — `null` when the model was not evaluated in that category.

| Field | Origin | Notes |
|---|---|---|
| `category` | backend-derived | Which split this block came from. |
| `metric_kind` | backend-derived | `score` for `agent`, `rating` for the rest. **Not comparable across kinds.** |
| `metric_value` | source-confirmed | `score` column for `agent`; `rating` for others. |
| `metric_lower` / `metric_upper` | source-confirmed | Confidence interval. `null` if not published. |
| `metric_variance` | source-confirmed | Only the rating categories publish it. |
| `sample_size` | source-confirmed | `observation_count` for `agent`, `vote_count` for others. |
| `session_count` | source-confirmed | `agent` only; `null` elsewhere. |
| `rank` | source-confirmed | Rank **within this category**, not global. |
| `model_name` | source-confirmed | Verbatim upstream spelling for *this* category — often a slug where `agent` uses a display name (`claude-opus-5-high` vs `Claude Opus 5 (High)`). Useful for auditing a match. |
| `organization`, `license` | source-confirmed | Verbatim. |
| `leaderboard_publish_date` | source-confirmed | `YYYY-MM-DD`. |
| `source_key` | backend-derived | The normalized key this upstream row was stored under. |
| `matched_by_fold` | backend-derived | `true` if reaching this row required the harness-wrapper fold. See [data-sources.md](data-sources.md). |

**`aa`** — the Artificial Analysis block. `null` fields mean **not measured**.

| Field | Origin | Notes |
|---|---|---|
| `id` | source-confirmed | AA's UUID. Stable. |
| `slug` | source-confirmed | AA's slug. AA has renamed these; `id` is the durable one. |
| `name` | source-confirmed | AA's display name, which often states the reasoning level (`GPT-5.5 (xhigh)`). |
| `creator.id` / `creator.name` | source-confirmed | `null` if AA publishes no creator. |
| `release_date` | source-confirmed | `YYYY-MM-DD`. |
| `intelligence_index_version` | source-confirmed | AA's index version — the numbers are only comparable within one version. |
| `intelligence_index`, `coding_index`, `agentic_index` | source-confirmed | Evaluation indices. |
| `intelligence_index_total_cost`, `cost_per_task` | source-confirmed | Money. |
| `pricing.*` | source-confirmed | USD per 1M tokens. |
| `performance.*` | source-confirmed | Throughput and latency medians. |
| `is_retained` | backend-derived | `true` = in this project's scope (present in LMArena's `agent` split). Always `true` on this endpoint. |
| `last_synced_at` | backend-derived | When we last refreshed this AA record. |

**`match`** — how the two sources were joined.

| Field | Origin | Notes |
|---|---|---|
| `method` | backend-derived | `alias` (a human asserted it), `exact_key`, `exact_name`, `exact_slug`, `exact_effort_slug`, or `harness_fold`. On live data the AA↔agent join is `exact_name`, `exact_slug` and `exact_effort_slug` only. |
| `confidence` | backend-derived | `1.0` for rungs whose key the sources themselves state (including `exact_effort_slug`, whose key is constructed from a stated level), `0.75` for `harness_fold`, the one genuine inference. Heuristic, for review tooling. |
| `is_manual` | backend-derived | `true` when a human asserted the match via `ModelAlias`. |
| `matched_key` | backend-derived | The `agent` key the AA record resolved to. |
| `last_matched_at` | backend-derived | When the join was last recomputed. |

---

## 2. `GET /categories/` — category index

Unpaginated. Lets you build tabs from real data and see an empty intersection
*before* requesting it.

```json
{
  "results": [
    {"category": "agent", "metric_kind": "score", "entry_count": 43,
     "in_agent_set_count": 43, "rank_min": 1, "rank_max": 43,
     "latest_publish_date": "2026-09-08"},
    {"category": "document", "metric_kind": "rating", "entry_count": 38,
     "in_agent_set_count": 12, "rank_min": 1, "rank_max": 38,
     "latest_publish_date": "2026-07-30"},
    {"category": "search", "metric_kind": "rating", "entry_count": 34,
     "in_agent_set_count": 2, "rank_min": 1, "rank_max": 34,
     "latest_publish_date": "2026-07-30"},
    {"category": "webdev", "metric_kind": "rating", "entry_count": 127,
     "in_agent_set_count": 35, "rank_min": 1, "rank_max": 127,
     "latest_publish_date": "2026-07-30"}
  ],
  "meta": {
    "generated_at": "...", "sources": { "..." : "..." },
    "primary_category": "agent",
    "matched_agent_models": 35
  }
}
```

`entry_count` is **distinct models**, not upstream rows: LMArena's `webdev` split
repeats models across rows (535 rows → 127 models) and we collapse them,
keeping the best-ranked row.

An empty category reports `metric_kind: null` and null rank bounds rather than
omitting the key, so the shape is constant.

---

## 3. `GET /categories/{category}/` — one category

`category` ∈ `agent` | `document` | `search` | `webdev`. Anything else is a `404`
listing the valid values.

**Single-source and unfiltered** — this endpoint does not apply the completeness
rule, so a row here may have no AA counterpart. That is the point: it is where
the excluded rows stay reachable.

### Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `in_agent_set` | bool | `true` | `false` returns rows excluded by the spec's intersection. |
| `scope` | `all` | — | Shorthand that drops the `in_agent_set` filter entirely. |
| `matched` | bool | — | `true`/`false` = has / has not an AA match. Omit for both. |
| `search`, `organization` | string | — | As `/overview/`. |
| `rank_min` / `rank_max` | int | — | |
| `min_metric` / `max_metric` | number | — | Note the names differ from `/overview/`'s `metric_min`/`metric_max`. |
| `min_sample_size` / `max_sample_size` | int ≥ 0 | — | |
| `ordering` | csv | `rank` | `rank`, `model_name`, `organization`, `metric_value`, `sample_size`, `session_count`, `leaderboard_publish_date`. |
| `page`, `page_size` | int | 1, 50 | |

### Response

```json
{
  "count": 43,
  "next": "...",
  "previous": null,
  "page_size": 50,
  "results": [
    {
      "model": {
        "key": "claude-opus-5-high",
        "name": "Claude Opus 5 (High)",
        "organization": "anthropic",
        "license": "Proprietary",
        "agent_key": "claude-opus-5-high",
        "in_agent_set": true
      },
      "category": { "...": "the same block shape as /overview/" },
      "matched_by_fold": false
    }
  ],
  "meta": {
    "generated_at": "...", "sources": { "...": "..." },
    "category": "agent",
    "metric_kind": "score",
    "in_agent_set": true,
    "scope": null
  }
}
```

`model.key` here is the row's own key for the requested category; `model.agent_key`
is the `agent` model it belongs to (`null` when not in the agent set — see
`?in_agent_set=false`). They differ where the sources spell a model differently
per category.

### Recipes

```
# what the dashboard shows
/categories/webdev/

# the rows the intersection excluded, i.e. why webdev has 127 models but 35
# in the agent set
/categories/webdev/?in_agent_set=false

# a model with data here but no AA match — the completeness rule's exclusions
/categories/agent/?matched=false

# everything, regardless of intersection
/categories/search/?scope=all
```

---

## 4. `GET /artificial-analysis/` — AA catalogue

**Single-source**, and the only endpoint that exposes AA records with no LMArena
presence.

### Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `retained` | bool | `true` | `true` = in this project's scope. `false` selects the **complement** (no agent-set presence), not the union. |
| `matched` | bool | — | Has / has not an LMArena match. |
| `search` | string | — | Substring of AA `name` or `slug`. |
| `creator` | string | — | Substring of creator name. |
| `intelligence_index_version` | number | — | Exact match. |
| `release_date_after` / `release_date_before` | date | — | Inclusive, `YYYY-MM-DD`. |
| `min_<field>` / `max_<field>` | number | — | Over the metric whitelist below. |
| `ordering` | csv | `-intelligence_index` | `name`, `slug`, `release_date`, `creator`, `last_synced_at`, or any metric name. |
| `page`, `page_size` | int | 1, 50 | |

**Metric whitelist** for `min_`/`max_` (also the `ordering` metric keys), echoed
back in `meta.metric_fields`:

`intelligence_index`, `coding_index`, `agentic_index`,
`intelligence_index_total_cost`, `cost_per_task`, `price_1m_input_tokens`,
`price_1m_output_tokens`, `price_1m_cache_hit_tokens`,
`price_1m_cache_write_tokens`, `median_output_tokens_per_second`,
`median_time_to_first_token_seconds`,
`median_time_to_first_answer_token_seconds`,
`median_end_to_end_response_time_seconds`.

An unknown metric filter is a `400` listing every allowed value, since silently
ignoring it would return data that looks filtered but is not.

### Response

```json
{
  "count": 30,
  "results": [
    {
      "aa": { "...": "the same block as /overview/, plus is_retained" },
      "matched_model": {
        "key": "claude-opus-5-high",
        "name": "Claude Opus 5 (High)",
        "organization": "anthropic",
        "match_method": "exact_name",
        "confidence": 1.0,
        "agent": { "...": "the agent category block" }
      }
    }
  ],
  "meta": {
    "generated_at": "...", "sources": { "...": "..." },
    "retained": true,
    "metric_fields": ["agentic_index", "...", "price_1m_output_tokens"]
  }
}
```

`matched_model` is `null` for an unmatched record — which is exactly how you find
them:

```
# AA models with no LMArena counterpart — the other half of the review queue
/artificial-analysis/?retained=false&matched=false
```

There is deliberately no parameter that lifts the retention filter entirely:
"everything AA publishes" is a review question, not a serving question. For the
whole catalogue, ask for both halves.

---

## 5. `GET /models/{key}/` — one model, every block

`{key}` resolves in this order: LMArena `agent` `model_key` → AA `slug` → AA
`id`. So the `model.key` you got from `/overview/` always works, and the two AA
spellings work as a convenience.

**Complete entries only.** The two `404` variants:

| Situation | Body |
|---|---|
| Model has no AA counterpart | `404 model_incomplete`, `reason: "no_aa_match"` |
| Model is AA-only, or exists in a non-agent category | `404 model_incomplete`, `reason: "not_in_agent_set"` |
| No such key at all | `404 not_found` |

### Response

The same `model`, `categories`, `aa` and `match` blocks as `/overview/`, plus:

```json
{
  "provenance": {
    "agent_key": "claude-opus-5-high",
    "aa_match_method": "exact_name",
    "aa_match_is_manual": false,
    "category_sources": {
      "document": {
        "source_key": "claude-opus-5-high",
        "source_name": "claude-opus-5-high",
        "matched_by_fold": false,
        "last_synced_at": "2026-09-11T10:52:52.648025Z"
      }
    },
    "lmarena_last_synced_at": "2026-09-11T10:52:52.648025Z"
  }
}
```

`provenance` is entirely `backend-derived`, and exists so a reviewer can see
*which upstream spelling* each block came from and whether the harness fold was
involved — from the API, not only the database. Useful in a "why is this number
attached to this model?" tooltip.

---

## 6. `GET /metadata/` — freshness and status

Unpaginated. The contract for "how old is this data, and is anything wrong".

```json
{
  "sources": {
    "lmarena": {
      "configured": true,
      "last_attempt_at": "2026-09-11T10:52:52.648025Z",
      "last_status": "success",
      "last_success_at": "2026-09-11T10:52:52.700000Z",
      "age_seconds": 0,
      "is_stale": false,
      "stale_after_seconds": 50400,
      "last_error": null,
      "fields_succeeded": ["agent", "document", "search", "webdev"],
      "fields_failed": {},
      "dataset_revision": "<hf revision hash>"
    },
    "artificial_analysis": {
      "configured": true,
      "last_attempt_at": "...", "last_status": "success", "last_success_at": "...",
      "age_seconds": 0, "is_stale": false, "stale_after_seconds": 50400,
      "last_error": null,
      "tier": "free",
      "rate_limit": {"limit": 100, "remaining": 78, "reset_at": "2026-09-12T10:06:24Z"},
      "pages_fetched": 4,
      "intelligence_index_version": 4.3
    }
  },
  "counts": {
    "lmarena_entries": 242, "lmarena_agent_entries": 43,
    "complete_agent_entries": 35, "aa_models": 652, "aa_models_retained": 35,
    "matches": 35, "unmatched_records": 904
  },
  "categories": [ "...": "identical to /categories/, for building tabs in one call" ],
  "matching": {"exact_name": 27, "exact_slug": 5, "exact_effort_slug": 3},
  "recent_runs": [ "...": "up to 5, newest first — see below" ],
  "config": {"harness_fold_enabled": true, "stale_after_seconds": 50400},
  "attribution": {
    "artificial_analysis": "https://artificialanalysis.ai/",
    "lmarena": "https://lmarena.ai/"
  },
  "meta": {"generated_at": "...", "sources": { "...": "the same blocks again" }}
}
```

### Reading the freshness block

Three **distinct** states, and they must render differently:

| State | Signal | Suggested UI |
|---|---|---|
| Never refreshed | `last_success_at: null`, `is_stale: true` | "Awaiting first refresh" |
| Configured off | `configured: false` (AA only, when no API key is set) | "Not configured" — not an error |
| Refresh failing | `last_status` is not `success`/`partial` | Warning banner; data is still the last good set |
| Simply old | `is_stale: true` with a `last_success_at` | "Data as of …" with an age |

`is_stale` is computed against `now` on every request (`age_seconds >
stale_after_seconds`, default 50400 s = 14 h — twice the 12-hour refresh
interval, so a single missed run does not raise the alarm).

**Success and freshness are never conflated.** A failed run keeps
`last_success_at` at the last good refresh and reports `last_error` alongside it,
because the data you are serving is still good — it is the *run* that failed.

`last_status` is `success`, `partial` (some LMArena field failed, the rest
landed), or `failed`.

### `recent_runs`

Per-run counters, newest first, including `dry_run: true` entries — a
`--dry-run` is listed here for operators to see but is **never** counted as a
refresh, so a rehearsal cannot silence the staleness alarm.

```json
{"id": 2, "source": "artificial_analysis", "status": "success",
 "triggered_by": "celery:beat", "dry_run": false,
 "started_at": "...", "finished_at": "...", "duration_ms": 4210,
 "records_seen": 646, "records_created": 0, "records_updated": 3,
 "records_unchanged": 643, "records_deactivated": 0, "records_failed": 0,
 "records_deduplicated": 0, "anomalies_recorded": 13,
 "error_code": null, "error_message": null}
```

### `counts`

| Key | Meaning |
|---|---|
| `lmarena_entries` | Active LMArena rows across all four categories. |
| `lmarena_agent_entries` | Active `agent` rows — the base model set. |
| `complete_agent_entries` | **What `/overview/` serves.** |
| `aa_models` | Active AA records. |
| `aa_models_retained` | Of those, in this project's scope. |
| `matches` | Live joins. |
| `unmatched_records` | Size of the review queue — both directions of the miss. |

---

## 7. `GET /unmatched/` — the review queue

Every row the joined endpoints drop, with a machine-readable reason. Unpaginated
count + paginated rows, same envelope as the others.

This is what keeps the completeness rule honest: **"not served" is never "not
knowable".**

### Parameters

| Param | Type | Default | Notes |
|---|---|---|---|
| `source` | `lmarena` / `artificial_analysis` | — | Invalid value → `404` listing valid ones. |
| `category` | `agent`/`document`/`search`/`webdev` | — | |
| `reason` | string | — | Free-form against the list below; an unknown one simply matches nothing. |
| `current` | bool | `true` | `false` shows records that stopped recurring. |
| `search` | string | — | Substring of `model_name`. |
| `ordering` | csv | `source,category,reason,model_key` | `source`, `category`, `reason`, `model_key`, `model_name`, `organization`, `occurrences`, `first_seen_at`, `last_seen_at`. |
| `page`, `page_size` | int | 1, 50 | |

### Reasons

| `reason` | `source` | Meaning and what to do |
|---|---|---|
| `no_aa_match` | `lmarena` | **An `agent` model with no AA record.** Exactly the rows `/overview/` drops. Confirm whether AA lacks the model or the normalizer needs an alias. |
| `no_lmarena_match` | `artificial_analysis` | An AA record with no `agent` counterpart. Same review, other direction. |
| `not_in_agent_set` | `lmarena` | A `document`/`search`/`webdev` model absent from the `agent` split. Usually expected — search-specialized models genuinely do not exist in `agent`. |
| `ambiguous_match` | either | More than one candidate matched, so we refused to guess. Read `detail`, then write an alias. |
| `duplicate_model_name` | either | Several upstream rows collapsed onto one normalized key (webdev: 535 rows → 127 models). The winner was kept; the loser is listed with both ranks. |
| `validation_failed` | either | The payload did not match the expected schema — usually means the upstream schema moved. Check `detail.field`. |
| `missing_identity` | either | No usable identity field (blank/missing name). |

### Response

```json
{
  "count": 905,
  "results": [
    {
      "source": "lmarena",
      "category": "agent",
      "reason": "no_aa_match",
      "model_key": "gpt-5-5-xhigh",
      "model_name": "GPT 5.5 (xHigh)",
      "organization": "anthropic",
      "occurrences": 3,
      "is_current": true,
      "first_seen_at": "2026-09-01T22:00:11Z",
      "last_seen_at": "2026-09-11T10:52:52.648025Z",
      "detail": {"rank": 2, "aa_records_considered": 646}
    }
  ],
  "meta": {"generated_at": "...", "sources": {"...": "..."}}
}
```

`occurrences` counts how many refreshes have reported the same record — high
values mean a persistent, not transient, gap.

`detail` is reason-specific and **not** a stable contract; treat it as review
context. Two keys worth knowing: `aa_records_considered` on `no_aa_match` means
"we compared against a complete catalogue of N records", which is what makes "AA
simply lacks it" a sound conclusion rather than an artefact of a partial read.

**Records are never deleted.** A record whose problem goes away gets
`is_current: false` and drops out of the default view (`?current=false` to see
it), because the ledger is rebuilt from each run rather than appended to.

---

## Errors

Every error body has an `error` string, so branch on that rather than parsing
prose.

| Status | `error` | When |
|---|---|---|
| 400 | `invalid_parameter` | A query parameter was malformed or not whitelisted. Carries `param` and, where a whitelist exists, `allowed`. |
| 404 | `unknown_value` | A path segment named something outside a closed set (e.g. a bad category). Carries `param` and `allowed`. |
| 404 | `model_incomplete` | The model exists but is excluded by the completeness rule. **Expected, not an error.** |
| 404 | `not_found` | No such key / page out of range. |
| 405 | `method_not_allowed` | Non-`GET`. |
| 429 | `throttled` | The per-IP rate limit was exceeded. Carries a `Retry-After` header. |
| 500 | `server_error` | |

```json
{"error": "invalid_parameter", "param": "ordering",
 "message": "Unknown ordering field 'cost'.", "allowed": ["aa_cost_per_task", "..."]}
```

Use `allowed` to render a message or correct the request; do not hard-code these
lists — they come from the server so they cannot drift.

`429` is the one error whose body nests, and the only one with a header worth
reading:

```json
{"error": "throttled",
 "detail": {"detail": "Request was throttled. Expected available in 42 seconds."}}
```

```
Retry-After: 42
```

`detail` is an **object** here, not a string — DRF raises the throttle as a
plain-detail exception, and every such exception is preserved under `detail` by
the same rule described above. Branch on `error`, and read the wait from the
`Retry-After` header rather than from the prose: the header is the contract, and
a client that parses the sentence breaks the day the wording changes.

`Retry-After` is sent on every 429 in practice, but it is **absent in one
narrow case** — if the configured rate was lowered while requests were already
counted, DRF can no longer compute a wait and omits the header rather than
inventing one. Treat its absence as "wait, duration unknown", not as zero.

---

## Freshness and missing data — the rules to build against

1. **`null` never means `0`.** Unmeasured stays null through the whole pipeline.
2. **A missing category block is information**, not a defect: the model was not
   evaluated there.
3. **`metric_kind` is not decoration.** `agent` publishes an Elo-style `score`
   (≈0.0–0.2); the others publish Bradley-Terry `rating`s (≈1000–1600). They are
   **not comparable** — do not plot them on one axis, and do not sort a mixed
   list by `metric_value`.
4. **Ranks are per-category**, not global.
5. **Everything is UTC, `Z`-suffixed.** `age_seconds` is the authoritative age;
   do not compute it from `last_success_at` against the client clock.
6. **Numbers are numbers.** Money is a JSON number, not a string.

### Coverage: what is and is not joined

Measured on live data, 2026-09-18:

| | Count |
|---|---|
| LMArena `agent` models | 46 |
| …with an AA match (`/overview/`) | **35** |
| …with no AA match (: `/unmatched/?reason=no_aa_match`) | 11 |
| AA records fetched | 652 |
| …retained (in the agent set) | 35 |

The 11 are not a bug to work around: AA and LMArena publish different model sets
and different reasoning levels, and the ladder is deliberately forbidden from
guessing (matching `-high` to a different effort level would attach the wrong
numbers). Where the two sources state the *same* level, the `exact_effort_slug`
rung reads it rather than guessing; the rest are named individually in
`/unmatched/`.

**If you need one of them:** the honest fix is a `ModelAlias` — a human asserting
the two records are the same model — not a query parameter that relaxes the
completeness rule. Adding one makes the model appear on `/overview/` from the
next refresh (twice daily), or immediately if an operator re-runs the AA
refresh. Do not add a client-side fuzzy join to fill the gap; it would put two
different numbers under one name with nothing recording which was which.

---

## Attribution requirement

Artificial Analysis's terms require a visible credit wherever their data is
shown. The URLs are published in `/metadata/`'s top-level `attribution` block —
so you can read them from the API rather than hard-coding them:

```json
"attribution": {"artificial_analysis": "https://artificialanalysis.ai/",
                "lmarena": "https://lmarena.ai/"}
```

That block is on `/metadata/` **only**. It is deliberately not repeated in the
pagination `meta` envelope, which carries `generated_at` and the freshness block
and nothing else — one call to `/metadata/` is the place to read it, and it is
already worth making once for `counts` and `freshness`.

Render it as a visible link on any view that shows AA metrics or AA-sourced
columns.

---

## CORS

The Django server allows the configured origins (`http://localhost:5173`, the
Vite dev server, by default — see `CORS_ALLOWED_ORIGINS` in `settings.py`).
`GET`, `HEAD` and `OPTIONS` are the only reachable methods, so if you are
developing against a different port, that port needs adding to the list rather
than working around.
