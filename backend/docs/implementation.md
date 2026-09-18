# Implementation notes

Architecture, the matching rules, the measured results, and every place the
built system differs from the design it was implemented from.

For the API surface see [api.md](api.md); for field provenance see
[data-sources.md](data-sources.md); for the review workflow see
[unmatched-report.md](unmatched-report.md).

---

## Architecture

One Django app, `leaderboard`. A second app would have added FK and migration
coupling and bought nothing; the required layers are separated as **modules**,
with a strictly one-way dependency direction:

```
api → selectors → models
tasks → services → clients + validation + matching + persistence → models
```

| Module | Responsibility |
|---|---|
| `models.py` | 7 models. Latest-only: one current row per entity, upserted per refresh. |
| `constants.py` | `TextChoices` enums, ordering whitelists, category→metric-kind map. |
| `normalization.py` | `normalize_model_key()`, `harness_fold()`. |
| `matching.py` | The deterministic match ladder — pure, no DB access except an injected alias table. |
| `validation.py` | `parse_aa_model()`, `parse_lmarena_row()`, `REQUIRED_COLUMNS`. Pure. |
| `persistence.py` | Every database write. Run bookkeeping, upserts, deactivation, the unmatched ledger. |
| `clients/` | `http.py` (`Transport` protocol, `RequestsTransport`, backoff policy), `artificial_analysis.py`, `lmarena.py`, `exceptions.py`. |
| `services/refresh.py` | Orchestration and transaction boundaries. `refresh_all` / `refresh_lmarena` / `refresh_aa`. |
| `locking.py` | Redis-backed non-blocking `run_lock()` (compare-and-delete on a token). |
| `tasks.py` | Thin `@shared_task` wrappers only — no logic. |
| `api/` | `urls`, `pagination`, `params`, `errors`, `selectors`, `serializers`, `views`. |
| `management/commands/` | `refresh_leaderboard`, `report_unmatched`. |

The single most important property of the request path is what it **cannot**
reach: `api/` imports no client, no transport and no `datasets`. A request cannot
make an external call because there is no code path to one, and
`tests/test_api_no_network.py` enforces it by making every outbound path raise
and asserting the endpoints still answer.

### Data model

- **`ModelCreator`** — AA creators, keyed by their UUID.
- **`LLMModel`** — current AA state, keyed by `aa_id` (**not** `slug`, so a slug
  rename updates the row rather than creating a twin).
- **`LMArenaEntry`** — current LMArena state, `UniqueConstraint(category,
  model_key)`, with `in_agent_set` / `agent_key` recording the intersection.
- **`ModelMatch`** — the AA↔agent join. A table rather than a column on
  `LLMModel`, because the method/confidence provenance *is* the review record.
- **`UnmatchedRecord`** — the reportable exclusions, with current-state (upsert)
  semantics so the table stays bounded and idempotent.
- **`SyncRun`** — ingestion status, freshness and per-run counters.
- **`ModelAlias`** — human-asserted joins, seeded by migration `0002`, editable
  in admin so a review-loop fix needs no deploy.

Two type rules: **money → `DecimalField`** (no drift when summing), **indices /
latency / throughput → `FloatField`**. Upstream `null` maps to DB `NULL` and
**never to `0`**.

---

## The matching ladder

Deterministic, conservative, and no similarity scoring anywhere. The rungs below
are shared; the AA↔agent join adds two of its own in the positions noted in
[rung order](#rung-order-name-before-slug).

1. **Alias override** — a `ModelAlias` row wins outright.
2. **Exact normalized key** — a unique hit matches; **multiple hits refuse** and
   record `ambiguous_match` with the candidate list. Never guessed.
3. **Harness-wrapper fold** — strip one whole trailing token from a tiny,
   evidence-based list (`codex-harness`), only when it yields exactly one
   candidate, guarded by a sibling check. See
   [data-sources.md](data-sources.md#the-harness-fold).
4. **Stated-effort slug** *(AA↔agent only)* — AA's slug with the effort level its
   `name` explicitly states appended. See
   [data-sources.md](data-sources.md#the-stated-effort-rung--exact_effort_slug).

Rungs 3 and 4 both derive the key they compare against rather than reading one
verbatim. Neither invents a candidate: each re-spells one a source already
stated. Only rung 3 is an *inference*, and it is the only one whose matches carry
`confidence < 1.0`.

### Rung order: `name` before `slug`

For the AA↔agent join the AA side keys on the normalized **`name` first**, and
falls back to `slug` **only when the name carries no effort parenthetical**.

This is not a stylistic choice. AA's bare slug can denote a *different reasoning
level* than the same record's name — slug `gpt-5-5` carries name
`"GPT-5.5 (xhigh)"`. Trying the slug first attaches the **xhigh** row to the
**base** model. Live confirmation of the corrected order:

```
gpt-5-5-xhigh   -> 'GPT-5.5 (xhigh)'   via exact_name
gpt-5-5         -> (no match)          <- and reported by name, see below
```

The slug rung remains necessary for records whose name carries no effort marker
at all (`mimo-v2-5-pro` → `"MiMo-V2.5-Pro"`), where it is safe.

**Between** the slug rung and the harness fold sits the **stated-effort rung**,
which is what resolves AA's verbose prose dialect. AA names the level in prose and
publishes that variant under the bare slug, while LMArena keys it with a suffix:

```
claude-opus-5-max  -> 'Claude Opus 5 (Adaptive Reasoning, Max Effort)'  via exact_effort_slug
```

`has_effort_marker` cannot see that prose, so the name rung misses and the slug
rung tries the bare `claude-opus-5` — which LMArena does not publish. The rung
appends the level AA stated, producing a key strictly *more specific* than the
slug, so unlike the fold it cannot reach a different effort level and needs no
sibling check.

### Reasoning effort is never folded

Covered in full in [data-sources.md](data-sources.md#rejected-folding-reasoning-effort).
The short version: simulating an effort fold on real data produced exactly one
match and it was **wrong** (`gpt-5.5-high` → `"GPT 5.5"` when `"GPT 5.5 (xHigh)"`
is the true sibling), and zero correct ones. A regression test pins it.

Folding *removes* a level. The stated-effort rung *adds* one the source itself
named, which is the difference between inferring an equivalence and reading an
explicit statement. It therefore does not reopen the fold.

**Consequence, by design:** a LMArena variant with no AA counterpart at the
*same* effort level stays unmatched. `Claude Fable 5 (High)` is the live example —
AA publishes Fable 5 at Max Effort only. Inheriting another level's numbers would
be worse than a visible gap; an alias is the escape hatch when a human decides
otherwise.

---

## Measured results (live data, 2026-09-18 sync)

The matched figures below are the post-stated-effort-rung state of the ladder. The
served join comes from the stored `ModelMatch` table, so `/overview/` reflects
them from the next AA refresh onwards — see
[alias promotion](#1-alias-promotion-takes-a-refresh-not-a-request), which is the
same mechanism.

| | Count |
|---|---|
| AA records fetched | 652 (4 pages) |
| AA records retained (in the agent set) | 35 |
| LMArena `agent` models | 46 |
| …with an AA match → shipped by `/overview/` | **35** |
| …with no AA match → `/unmatched/?reason=no_aa_match` | 14 → **11** |

Matches by rung: **27** `exact_name`, **5** `exact_slug`, **3**
`exact_effort_slug` (the three rows this rung was added for), **0**
`harness_fold` on the AA side.

| Category | Stored rows (post-dedupe) | In `agent` set |
|---|---|---|
| `agent` | 46 | 46 |
| `document` | 44 | 17 |
| `search` | 34 | 2 |
| `webdev` | 128 | 37 |

Ledger: **615** `no_lmarena_match`, **149** `not_in_agent_set`, **128**
`duplicate_model_name`, **11** `no_aa_match`, **1** `ambiguous_match` — 904
current records.

Dedupe is doing real work rather than bookkeeping: the stored `webdev` count is
what survives several upstream rows per model collapsing onto one key (535 raw
rows → 127 models at the 2026-09-11 sync).

---

## Scheduling

`django-celery-beat` with `DatabaseScheduler`, and the schedule declared in
`CELERY_BEAT_SCHEDULE` so it stays code-reviewable while living in editable DB
rows:

```python
CELERY_BEAT_SCHEDULE = {
    "leaderboard-refresh-twice-daily": {
        "task": "leaderboard.refresh_all",
        "schedule": crontab(minute=0, hour="8,20"),   # Asia/Shanghai → 00:00 / 12:00 UTC
        "options": {"expires": 3600},
    }
}
```

Only the orchestrator is scheduled; `refresh_lmarena` and `refresh_aa` exist as
thin tasks for ops and manual use. `expires: 3600` means a run that could not
start within an hour is dropped rather than firing late, immediately before the
next one.

**`refresh_all` runs LMArena first, then AA, in-process** — not `.delay()` — because
AA retention and matching both read the agent set just written.

Overlap prevention in two layers: the Redis `run_lock` (a held lock means *skip*,
never queue) **and** a conditional unique index on `SyncRun`
(`UniqueConstraint(fields=["source"], condition=Q(status="running"))`), which
holds even if the cache is unavailable. `reap_stale_running()` fails `running`
rows older than 6 h so a SIGKILLed worker cannot strand one and block every
future refresh.

### The schedule presumes a machine that is always on

Which a development machine is not. With only `runserver` up, nothing refreshes
and the board silently ages past any threshold, so `refresh_if_stale` exists to
be run ahead of the server in a start script. It is deliberately a **command,
not a startup hook**: an `AppConfig.ready()` handler or a `runserver` override
would fire inside `migrate`, `shell` and every test run, and would put a network
fetch on the import path of the process that is supposed to be unable to reach
the network.

Its staleness test is `last_success_at` against `stale_after_seconds()` — the
same two helpers `/metadata/` uses, so the command and the API can never disagree
about what "stale" means. On top of that sits a cooldown measured from the last
*attempt* rather than the last success: without it, a refresh that fails would be
re-attempted on every boot of a crash-looping or file-watching process, and each
AA attempt can spend 4 of the 100 requests shared across the whole organization
per day. The two gates answer different questions — "is the data old?" and "have
we already tried recently?" — and `_quota_exhausted()` inside the AA phase is a
third, independent one.

A failed refresh exits 0. The API is built to serve the last good data with
`is_stale: true` when a source is down, so blocking a launch on a failed fetch
would defeat the property the whole read path is designed around; `--strict` is
the opt-in for the opposite preference.

### The timezone bug that had to be fixed first

The scaffold shipped `CELERY_TIMEZONE = "China/Shanghai"`, which is **not a valid
IANA zone**: `ZoneInfo("China/Shanghai")` raises `ZoneInfoNotFoundError` in this
environment, so **Celery beat could not start at all**. Corrected to
`Asia/Shanghai`. Django `TIME_ZONE` stays `UTC` and every API timestamp is
explicit UTC ISO-8601.

---

## "Don't destroy the last good data"

Enforced at the persistence layer, as five rules:

1. **No `DELETE` against any source table.** A vanished model is deactivated
   (`is_active=False`) so the previous state stays inspectable. The one
   exception is `ModelMatch`, which is *derived*: it is rebuilt inside the
   transaction that writes the run's data, so a failure rolls the rebuild back
   along with everything else and the previous matches survive.
2. **All writes for one source in a single `transaction.atomic()`.** Network I/O
   never happens inside a transaction.
3. **A failed run records `failed` + `error_code`** and leaves previous rows
   untouched; `last_success_at` still reports the last good refresh. Success and
   freshness are never conflated.
4. **`deactivate_missing` runs only on a fully successful fetch with records
   seen.** A partial or empty response must never be able to blank the board —
   this is the specific failure mode the rule exists for.
5. **A 200 with zero models raises** and fails the run rather than emptying the
   table.

SQLite concurrency: WAL (`PRAGMA journal_mode=WAL` in `AppConfig.ready()`,
wrapped in `try/except OperationalError`) plus
`OPTIONS = {"timeout": 20, "transaction_mode": "IMMEDIATE"}`. Without WAL, the
API can observe a half-written state while the worker writes — a real concern
here, not a theoretical one.

---

## Inbound rate limiting

DRF's own throttling, cache-backed, two stacked budgets per client IP
(`DEFAULT_THROTTLE_CLASSES` in `REST_FRAMEWORK`). Nothing new was added to the
dependency list, and the 429 body needed no code at all: `errors.py` already
mapped 429 to `{"error": "throttled", ...}`, and DRF already emits `Retry-After`
from the exception's `wait`.

Three decisions are worth the space they take:

**It fails open.** `allow_request` catches a cache-backend failure and returns
allow, logging a warning — the same stance `locking.py` takes for the refresh
lock, and for the same reason. Every response here is served from SQLite; Redis
holds only the counters. Letting a Redis outage 500 the API would trade a total
outage for a lost rate limit, which is strictly worse than the problem it solves.

**`NUM_PROXIES` is pinned to 0.** DRF's default is `None`, under which
`get_ident` returns `X-Forwarded-For` verbatim whenever the header is present.
Since any client can write that header, the default configuration is one a
determined caller escapes by sending a different value per request — a rate
limit that looks present in the config and is absent in practice. `0` uses the
socket peer, which is correct while nothing sits in front of the app.

**The rates and the kill switch are read per request.** DRF binds
`APIView.throttle_classes = api_settings.DEFAULT_THROTTLE_CLASSES` when
`rest_framework.views` is first imported, and `SimpleRateThrottle` binds
`THROTTLE_RATES` the same way, so a value consulted at import could never be
overridden — `LEADERBOARD_THROTTLE_ENABLED` would be a setting that does nothing
once the module is loaded. `get_rate()` therefore reads `api_settings` on every
call, which is also what makes the limits testable without a 61-request test.

The gap that leaves is a malformed rate string: `parse_rate` runs inside the
throttle's constructor, *outside* the fail-open guard, so a typo would be a 500
on every request. `leaderboard/checks.py` closes it at boot, where the codebase
already prefers this class of failure to surface (`CELERY_TIMEZONE` is the same
argument).

## Testing

**300 tests, ~3 s.** Run with `uv run pytest`.

The governing rule is **inject at our own seams, never at a library boundary**:

| Seam | What it replaces |
|---|---|
| `Transport` protocol | `requests` — the AA client takes a transport, so retry, pagination and header parsing are tested against a fake that records every call and every `sleep`. |
| injected `load_dataset` callable | `datasets` — constructor-injected, which also *guarantees* the DRF process never imports `datasets`. |
| `refresh.build_lmarena_client` / `build_aa_client` | The service's real client factories, so command and task tests drive the whole pipeline without patching anything global. |

The two tests worth knowing about:

* **`test_api_no_network.py`** — patches the HTTP transport, the socket, and the
  dataset loader to raise, then asserts every endpoint still answers. This is the
  single most important test: it enforces "requests never trigger live external
  calls" at the request layer rather than by review.
* **`test_end_to_end.py`** — fakes → `refresh_all()` → assert the DB → hit every
  endpoint → **fail the AA transport and re-run** → assert every served value is
  byte-identical and that metadata reports the failure alongside the previous
  `last_success_at`. Nothing under `results` may move; only
  `meta.sources.*` bookkeeping.

---

## Deliberate deviations from the design

Recorded because each one changes behaviour a reader might otherwise expect from
the plan.

### 1. Alias promotion takes a refresh, not a request

**The design said** a `ModelAlias` "promotes an entry to complete on the very
next request with no refresh and no deploy", and one section of the plan
explicitly promised the filter would be "applied in the selector at read time".

**What is built:** the completeness rule *is* read-time (it is a queryset filter
on the live match, never a stored flag), but **alias resolution runs in the match
ladder during a refresh**. So an alias takes effect on the next refresh —
scheduled, or immediately with one command:

```bash
uv run python manage.py refresh_leaderboard --source=artificial_analysis
```

**Why it cannot be otherwise:** the match must be a stored fact, because
`/overview/`, `/models/{key}/` and `/unmatched/` all read it and must agree. A
per-request inference could answer differently on two endpoints in the same
second — a model listed by `/overview/` while its own page 404s. Proved by probe,
not by reasoning: adding an alias then re-requesting left `/overview/` at 2 rows;
re-running the AA refresh produced 3 with `method: "alias"`.

The four places that claimed otherwise (in `aliases.py`, `models.py`,
`admin.py`, `selectors.py`) were corrected. `test_end_to_end.py::TestAliasPromotion`
pins both halves: nothing moves mid-request, and the next refresh promotes with
its provenance intact.

**What a reviewer still never needs:** a deploy, a code change, or a backfill
job.

### 2. Dry runs no longer count as successful refreshes

A real defect, found by chasing a test failure. `last_success_at()` and
`source_freshness()` both counted `dry_run=True` rows as refreshes.

**The failure it would have caused:** a `--dry-run` writes no data — it rolls its
whole transaction back — yet it would have set `last_success_at`, making a
day-old board report `is_stale: false` and **switching off the one alarm that
says the data has stopped arriving**. An operator checking the match rate before
a change would have silenced the staleness warning.

**Fixed** in both places, with `test_a_dry_run_does_not_make_the_data_look_fresh`
pinning it. Dry runs deliberately remain visible in `/metadata/`'s `recent_runs`
with `dry_run: true`.

One thing was deliberately **not** filtered this way: the quota preflight. A dry
run *does* make real HTTP calls and consume the shared AA quota, so excluding it
there would misreport the remaining budget.

### 3. Agent-side misses are now recorded

**The design promised** that the agent models with no AA record are "exactly the
entries the completeness rule removes from `/overview/`, **listed by name** so a
human can confirm whether AA simply lacks them or our normalizer needs an
alias."

**What was built initially:** nothing recorded them. Every ledger write in the AA
phase was AA-sourced, and `UnmatchedReason` had no value for this direction — so
the single population the completeness rule hides was invisible in
`/unmatched/`. Found on live data: 43 agent models, 30 matched, 13 missing, and
**zero** `('lmarena', 'agent', ...)` ledger rows.

**Fixed** by adding `UnmatchedReason.NO_AA_MATCH` (migration `0004`), recording
one row per unmatched agent model during the AA matching phase, teaching
`report_unmatched` its help text, and pointing `ModelDetailView`'s
`no_aa_match` 404 at the new record. The live 13 now report as:

```
| lmarena | agent | no_aa_match | Claude Fable 5 (High)  | `claude-fable-5-high`    | 3 | {"rank": 5,  "aa_records_considered": 652} |
| lmarena | agent | no_aa_match | GPT 5.5                | `gpt-5-5`                | 3 | {"rank": 20, "aa_records_considered": 652} |
| ... 9 more
```

`aa_records_considered` is what makes the review question answerable: it records
that the comparison ran against a **complete** catalogue read, so "AA simply
lacks it" is a sound conclusion rather than an artefact of a partial fetch.

**This cost `UnmatchedLedger` a `reasons=` scope**, which is worth understanding
because the bug it prevents is silent. That new row is *LMArena-sourced* but
written by the *AA* phase, so two ledgers now own rows of the same source.
An unscoped `close_stale()` in either would flag the other's fresh rows stale —
and since `/unmatched/` defaults to `current=true`, the population would simply
vanish from the report. Proved by reverting the scoping: the
`not_in_agent_set` rows written moments earlier by the same `refresh_all`
disappear. `test_the_two_ledgers_do_not_close_each_others_rows` pins all three
directions.

### 4. AA↔agent coverage is 35/46, not the projected ~34/43

The design projected ~34 agent models matched, measured "under exact-normalized
matching" with slug-or-name matching, and asked for the figure to be re-measured
once the rung order was corrected — warning that it could stay "similar" with the
difference being *correct* rather than *more* matches.

It came out at **30** of the 43 agent models then published, against a catalogue of
646. The direction of the warning was right; the magnitude was -4. The corrected
rung order attaches effort-specific AA rows to the *correct* agent variant, which
necessarily leaves the bare base variants (`gpt-5-5`, `gpt-5-4-high`, …) unmatched
rather than wrongly attached.

The stated-effort rung later recovered **3** of those, taking it to **35 of 46** —
but only the three where the two sources actually *agree* on the level and our
reading of AA's prose was what failed (`claude-opus-5-max`, `claude-fable-5-1-max`,
`deepseek-v4-1-flash-max`). The remaining **11** are still the review queue, and
they are still unmatched for the original reason: the sources genuinely disagree,
or AA lacks the entry. Deviation 3 remains the explanation for most of them.

### 5. `purge_legacy_tables` was not written

The design listed an optional
`management/commands/purge_legacy_tables.py`, to refuse-run unless the orphan
`api_*` tables in the old `db.sqlite3` were empty.

It turned out to be unnecessary: the stale migration rows
(`api_modelcreator`, `api_llmmodel`, `api_modelsnapshot`, `api_syncrun`, all 0
rows) belong to the app label `api`, and this project's app is `leaderboard`, so
`migrate` never collides with them. A command whose only job is to allow a
deletion nobody needs is a command that invites an accidental one.

**Consequence:** an existing `db.sqlite3` carries four unused empty tables. They
are inert — no model, no migration and no code path refers to them.

---

## Known limitations

- **LMArena exposes no stable model id.** Identity rests on the normalized
  `model_name`. A rename upstream reads as a new model plus a deactivated old
  one.
- **`latest` only — no historical backfill.** The `full` splits are deliberately
  unused, and there are no snapshot tables.
- **`agent` (`score`) and the other categories (`rating`) are not on a comparable
  scale.** `metric_kind` records which is which; ranks are per-category, not
  global.
- **`search` intersects to 2 models and `document` to 12.** Inherent to the
  source: search-specialized models genuinely are not in the `agent` split.
- **Harness-fold matches are inferred joins.** Auditable, individually listed,
  and promotable to explicit aliases.
- **Reasoning-effort *differences* are never inferred**, so genuinely related
  models stay unmatched until a human aliases them. Unmatched is the correct
  default when the alternative is a confident wrong answer. Where the two sources
  state the *same* level, the stated-effort rung reads it rather than inferring
  it — the distinction is in
  [data-sources.md](data-sources.md#rejected-folding-reasoning-effort).
- **AA quota is 100 requests / 24 h, shared across the whole organization.** A
  full refresh is 4; steady state is 8/day. If the org's other keys spend it,
  scheduled refreshes fail with `rate_limit_exceeded` and the API keeps serving
  the last good data with `is_stale: true`.
- **A match can regress** if AA renames slugs or changes effort naming. The
  unmatched report and the `ModelAlias` table are the recovery path.
- **The battle-count heatmap from the proposal is out of scope**: the leaderboard
  dataset does not publish pairwise comparison counts.
- **The joined surface is intentionally the smallest of the three.** `/overview/`
  and `/models/{key}/` show 35 entries; `/categories/{category}/` and
  `/artificial-analysis/` show more, being single-source views. If the frontend
  needs a model that is not on `/overview/`, the honest fix is a `ModelAlias` —
  not a query parameter that relaxes the completeness rule.
