# llm-picker — backend

Django backend for the LLM leaderboard frontend. Ingests two external sources
into a local database and serves them over a versioned read-only API.

* **LMArena** — the `lmarena-ai/leaderboard-dataset` Hugging Face dataset
  (`agent`, `document`, `search`, `webdev`).
* **Artificial Analysis** — API v2 (`/api/v2/language/models/free`).

**Requests never trigger an external call.** Everything is fetched by a
twice-daily Celery schedule and served from SQLite, so the API's latency and
availability do not depend on either upstream. This is enforced by a test that
makes every outbound path raise and asserts the endpoints still answer.

---

## Quick start

```bash
# 1. dependencies (Python 3.13, uv)
uv sync --group dev

# 2. configuration
cp .env.example .env
#    then set AA_API_KEY -- or leave it blank and the read-only API still works,
#    reporting that source as `"configured": false`

# 3. schema
uv run python manage.py migrate

# 4. data. Only step that needs network + the AA key.
uv run python manage.py refresh_leaderboard --source=all

# 5. serve
uv run python manage.py runserver
```

Then: <http://localhost:8000/api/v1/leaderboard/overview/>

**Get the API key last, not first.** Steps 1–3 and 5 all work without one, so
frontend work is never blocked on a key. Step 4 is the only one that needs it.

### The three long-running processes (for the schedule)

```bash
redis-server                                                    # broker + lock
uv run celery -A llm_picker_backend worker -l info              # executes refreshes
uv run celery -A llm_picker_backend beat   -l info              # schedules them
```

Beat is only needed for the automatic twice-daily refresh. Without it, nothing
refreshes on a schedule — which is the normal state of a dev machine, where
`runserver` is the only process up and the board quietly ages. Put
`refresh_if_stale` in front of the server instead:

```bash
uv run python manage.py refresh_if_stale    # fetches only if the data has aged out
uv run python manage.py runserver
```

It exits 0 whether the data was fresh, refreshed, skipped or the refresh failed,
so it never blocks a launch — the API serves the last good data either way.

---

## Commands

```bash
# Refresh. `--dry-run` fetches and matches for real, then rolls back -- it
# writes nothing, and it is never counted as a refresh in the freshness block.
uv run python manage.py refresh_leaderboard --source=all
uv run python manage.py refresh_leaderboard --source=artificial_analysis
uv run python manage.py refresh_leaderboard --source=lmarena --dry-run
uv run python manage.py refresh_leaderboard --source=all --dry-run --no-lock

# Launch-time. Refreshes both sources only if the stored data has aged past
# LEADERBOARD_STALE_AFTER_SECONDS, and only if no attempt was made within the
# cooldown. `--check` reports without fetching; `--force` ignores both gates;
# `--strict` exits non-zero if a refresh was attempted and failed.
uv run python manage.py refresh_if_stale
uv run python manage.py refresh_if_stale --check

# Review what did not join. See docs/unmatched-report.md for the workflow.
uv run python manage.py report_unmatched
uv run python manage.py report_unmatched --reason=no_aa_match --format=md

# Tests (~300, a few seconds)
uv run pytest
uv run pytest leaderboard/tests/test_end_to_end.py -v
```

| `--source` value | Note |
|---|---|
| `all` | LMArena first, then AA — AA's retention and matching read the agent set just written. |
| `lmarena` | |
| `artificial_analysis` | **Not** `aa` — the value is validated, and a wrong one is rejected. |

`--dry-run` **does** make real HTTP calls, including against the AA quota. It
skips only the writes.

---

## Layout

```
llm_picker_backend/     settings, urls, celery app
leaderboard/
  models.py            7 models, latest-only
  constants.py         enums, ordering whitelists, category→metric-kind map
  normalization.py     normalize_model_key(), harness_fold(), effort_from_name()
  matching.py          the deterministic match ladder
  validation.py        parse_aa_model(), parse_lmarena_row() — pure
  persistence.py       every database write; the unmatched ledger
  services/refresh.py  orchestration and transaction boundaries
  clients/             Transport protocol, AA client, LMArena client
  api/                 urls, views, selectors, serializers, params, errors
  tasks.py             thin @shared_task wrappers
  management/commands/ refresh_leaderboard, report_unmatched
  tests/               fakes, factories, and the suite
docs/                  api.md, implementation.md, data-sources.md, unmatched-report.md
```

Dependency direction is strictly one-way: `api → selectors → models`, and
`tasks → services → clients + validation + matching + persistence → models`.
`api/` imports no client, no transport and no `datasets` — which is *why* a
request cannot reach the network.

---

## Configuration

Everything is env-var driven with working defaults; `.env.example` documents the
full set. The ones that matter:

| Variable | Default | Note |
|---|---|---|
| `AA_API_KEY` | *(empty)* | **Secret. Never commit it.** Leave blank and only the AA refresh fails. |
| `DJANGO_SECRET_KEY` | dev value | Generate one for anything non-local. |
| `DJANGO_DEBUG` | `true` | `true` also allows any localhost dev port through CORS. |
| `REDIS_URL` | `redis://127.0.0.1:6379` | Broker `/0`, results `/1`, lock cache `/2`. |
| `CELERY_TIMEZONE` | `Asia/Shanghai` | Must be a **real IANA zone** — see below. |
| `LEADERBOARD_STALE_AFTER_SECONDS` | `50400` (14 h) | Twice the 12 h schedule, so one missed run is not an alarm. Shared by `/metadata/` and `refresh_if_stale`. |
| `LEADERBOARD_ENABLE_HARNESS_FOLD` | `true` | The one *inferred* join in the ladder (the `harness_fold` rung, the only one scoring below `confidence` 1.0). |
| `LEADERBOARD_STARTUP_REFRESH_COOLDOWN_SECONDS` | `1800` (30 min) | Minimum gap between `refresh_if_stale` attempts, whatever the previous one's outcome. Protects the shared AA quota from a restart loop. |
| `LEADERBOARD_THROTTLE_ENABLED` | `true` | Master switch for the API's rate limit. |
| `LEADERBOARD_THROTTLE_BURST` | `60/min` | Per-IP burst ceiling. |
| `LEADERBOARD_THROTTLE_SUSTAINED` | `2000/day` | Per-IP daily ceiling. |
| `DJANGO_NUM_PROXIES` | `0` | **Security setting.** `0` ignores `X-Forwarded-For` and uses the socket peer. See below. |

### ⚠️ `CELERY_TIMEZONE` must be a valid IANA zone

The scaffold shipped `China/Shanghai`, which is **not** a valid IANA name:
`ZoneInfo("China/Shanghai")` raises `ZoneInfoNotFoundError`, so **Celery beat
could not start at all**. It is now `Asia/Shanghai`. If you copy a config from
anywhere, check this value first — and note the `test_beat_schedule` tests
resolve the configured zone, so a bad value fails the suite rather than failing
silently at 8am.

---

## The API

Base path `/api/v1/leaderboard/`. Seven read-only `GET` endpoints — `overview`,
`categories`, `categories/{category}`, `artificial-analysis`, `models/{key}`,
`metadata`, `unmatched`.

**The one thing to know before reading the docs:**
`/overview/` and `/models/{key}/` serve **complete entries only** — an LMArena
`agent` row *and* a matched Artificial Analysis record. On live data that is 35
of 46 agent models. A real-but-unmatched model is a `404 model_incomplete` with
the reason in the body — an expected state, not an error to escalate. Every
excluded row stays reachable through `/categories/{category}/`,
`/artificial-analysis/` and `/unmatched/`.

### Rate limiting

Since this is meant to be a free public API, every endpoint is limited per client
IP: **60 requests/minute** and **2000 requests/day**, both enforced, both
configurable (`LEADERBOARD_THROTTLE_BURST` / `LEADERBOARD_THROTTLE_SUSTAINED`).
Exceeding either returns `429` with the usual `{"error": "throttled", ...}` body
and a `Retry-After` header.

Two properties are worth knowing before changing anything here:

* **It fails open.** The counters live in Redis, but the data does not — every
  response is served from SQLite. If the cache is unreachable the request is
  served *uncounted* and a warning is logged, because trading a total outage for
  a lost rate limit is the wrong way round. (The refresh lock degrades the same
  way, for the same reason.)
* **It does not trust `X-Forwarded-For` by default.** That header is client-
  writable, so believing it with no proxy in front would let anyone mint a new
  identity per request and never be counted — which is DRF's own default
  behaviour. `DJANGO_NUM_PROXIES=0` means "use the socket peer". Raise it to the
  number of proxies you control *only* once one is actually deployed.

A malformed rate is caught by `manage.py check` at boot, not by a 500 per request
— see `leaderboard/checks.py`.

Full reference: **[docs/api.md](docs/api.md)** — start there for frontend work.

| Document | Contents |
|---|---|
| [docs/api.md](docs/api.md) | Every endpoint, parameter, field (with origin markers) and error. The frontend deliverable. |
| [docs/implementation.md](docs/implementation.md) | Architecture, the matching ladder, measured results, deviations, known limitations. |
| [docs/data-sources.md](docs/data-sources.md) | Source-field → DB-column provenance, normalization, rate-limit budgets, licenses. |
| [docs/unmatched-report.md](docs/unmatched-report.md) | Sample report output and the review workflow. |

---

## Notes for whoever runs this

* **AA's free tier is 100 requests / 24 h, shared across every key in the
  organization.** A full refresh costs 4; twice daily is 8. If the quota is
  exhausted the run fails with `rate_limit_exceeded` and the API keeps serving
  the last good data with `is_stale: true` — the correct behaviour, not a bug to
  work around by refreshing harder.
* **A failed refresh never damages stored data.** No source table is ever
  `DELETE`d; a vanished model is deactivated instead. `deactivate_missing` only
  runs after a complete, non-empty fetch, so a partial response cannot blank the
  board.
* **SQLite runs in WAL mode** with a 20 s busy timeout, because the Celery worker
  writes while `runserver` reads the same file.
* **`ModelAlias` rows are the fix for a missing join** — not a code change, not a
  deploy, and not a looser query. See
  [docs/unmatched-report.md](docs/unmatched-report.md).
* **License/attribution:** Artificial Analysis requires a visible credit wherever
  their data is displayed. The URL is served in `/metadata/`'s `attribution`
  block so the frontend reads it rather than hard-coding it.
