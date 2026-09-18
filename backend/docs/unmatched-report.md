# The unmatched report — reviewing what did not join

Every record this project refuses to join is stored and reported. Nothing is
dropped silently, and nothing is guessed at.

Two readers:

* **Ops** — `manage.py report_unmatched`, for a terminal or a Markdown ticket.
* **Frontend** — `GET /api/v1/leaderboard/unmatched/`, so the review queue is
  visible in the product rather than only on the server.

Both read the same `UnmatchedRecord` table, so they cannot disagree.

---

## Running it

```bash
# everything current, as a table (default)
uv run python manage.py report_unmatched

# just the models the joined endpoints drop — the usual review loop
uv run python manage.py report_unmatched --reason=no_aa_match --format=md

# one direction of the AA review: AA records with no LMArena counterpart
uv run python manage.py report_unmatched --source=artificial_analysis --reason=no_lmarena_match

# include records that stopped recurring (hidden by default)
uv run python manage.py report_unmatched --all

# machine-readable, for a script or a diff between two runs
uv run python manage.py report_unmatched --format=json
```

| Flag | Meaning |
|---|---|
| `--source` | `lmarena` or `artificial_analysis` |
| `--category` | `agent` / `document` / `search` / `webdev` |
| `--reason` | One of the reasons below (validated against the enum — an unknown one is rejected, not ignored) |
| `--format` | `table` (default), `md`, `json` |
| `--search` | Substring of model key or name |
| `--limit` | Truncate, **saying what it hid** (never silently) |
| `--all` | Include records whose problem stopped recurring |

`--limit` reports how many rows it omitted — a truncated report that does not say
so is a report that lies about coverage.

---

## What the output looks like

Real output, live data, 2026-09-18:

```
source                category    reason                    model_name                                      model_key
------------------------------------------------------------------------------------------------------------------
artificial_analysis   agent       no_lmarena_match          A.X-K2                                          a-x-k2
artificial_analysis   agent       no_lmarena_match          Agnes 2.5 Pro Alpha                             agnes-2-5-pro-alpha
artificial_analysis   agent       no_lmarena_match          Agnes 2.5 Pro Beta                              agnes-2-5-pro-beta
...
(showing 5 of 904 rows)

Detail:
  a-x-k2: {"name_key": "a-x-k2", "slug_key": "a-x-k2", "name_states_effort": false, "slug_rung_skipped": false}
  claude-fable-5: {"name_key": "claude-fable-5-adaptive-reasoning-max-effort-opus-4-8-fallback", "slug_key": "claude-fable-5", "name_states_effort": false, "slug_rung_skipped": false, "effort": "max", "effort_key_tried": "claude-fable-5-max"}

By reason:
     615  no_lmarena_match
          An AA record with no LMArena `agent` counterpart. Review whether AA
          simply lacks the model or our normalizer needs an alias.
     149  not_in_agent_set
          A document/search/webdev model absent from the `agent` split. Usually
          expected -- search-specialized models genuinely do not exist in agent.
     128  duplicate_model_name
          Several upstream rows collapsed onto one normalized key. The winner was
          kept; the loser is listed here with both ranks.
      11  no_aa_match
          An LMArena `agent` model with no AA record at the same reasoning level.
          These are exactly the entries the completeness rule removes from
          /overview/ -- confirm whether AA lacks the model or an alias is needed.
       1  ambiguous_match
          More than one candidate matched, so the ladder refused to guess. Read
          `detail`, then write an alias naming the intended target.
```

`--format=md` emits a table ready to paste into a ticket:

```
| Source | Category | Reason | Model | Key | Seen | Detail |
| --- | --- | --- | --- | --- | --- | --- |
| lmarena | webdev | duplicate_model_name | claude-fable-5 | `claude-fable-5` | 4 | {"kept_name": "claude-fable-5", "kept_rank": 2, "dropped_rank": 12} |
| lmarena | webdev | duplicate_model_name | claude-fable-5.1-max | `claude-fable-5-1-max` | 3 | {"kept_name": "claude-fable-5.1-max", "kept_rank": 2, "dropped_rank": 3} |
```

Pipes inside values are escaped, so a model name containing `|` cannot break the
table.

**`Seen`** is `occurrences` — how many refreshes have reported the same record.
A high number means a persistent gap, not a transient blip: worth acting on. A
`1` may resolve itself on the next run.

---

## The reasons

| Reason | Source | Action |
|---|---|---|
| `no_aa_match` | `lmarena` | **The highest-value review.** An `agent` model with no AA record — exactly what `/overview/` drops. |
| `no_lmarena_match` | `artificial_analysis` | An AA record with no agent counterpart. Same question, other direction. Mostly AA's much broader catalogue. |
| `not_in_agent_set` | `lmarena` | A `document`/`search`/`webdev` model absent from `agent`. **Usually expected** — do not "fix" these. |
| `duplicate_model_name` | either | Several upstream rows collapsed onto one key. The winner was kept; the loser is listed with both ranks. Correct by design. |
| `ambiguous_match` | either | Two or more candidates matched, so we refused to guess. Needs a human. |
| `validation_failed` | either | A payload did not match the expected schema — usually means the upstream schema moved. Check `detail.field`. |
| `missing_identity` | either | No usable identity field (blank or missing name). |

### Which ones actually need a human

Most rows in the report are **correct behaviour, listed for auditability**:

* The 615 `no_lmarena_match` + 149 `not_in_agent_set` + 128
  `duplicate_model_name` are largely the shape of the two sources' model sets
  rather than defects. AA publishes 652 models; LMArena's `agent` split has 46.
  They *should* not join.
* The rows worth working are the ones where **the two sources almost certainly do
  describe the same model**: `no_aa_match` (11 today) and `ambiguous_match` (1),
  plus any `validation_failed` (a schema change is a real bug).

When a `no_lmarena_match` row carries `effort` in its detail, the ladder read a
reasoning level off the AA name and tried `<slug>-<level>` (shown as
`effort_key_tried`) against the agent set. That is the rung that resolves AA's
verbose prose; a row that has `effort` but no `effort_key_tried` was suppressed by
the guard because its slug already names the level. Either way, an absent key
means LMArena publishes nothing at that level — see
[data-sources.md](data-sources.md#the-stated-effort-rung--exact_effort_slug).

A fast way to separate them: sort your attention by `occurrences` — a gap that
has survived several refreshes is a stable disagreement between the sources
rather than a timing artefact.

---

## The review workflow

**1. Start with the models the product actually hides** — the completeness rule's
exclusions:

```bash
uv run python manage.py report_unmatched --reason=no_aa_match --format=md
```

**2. For each one, answer: does AA publish this model at this reasoning level?**

Open AA's site and search the `model_name` verbatim. Three outcomes:

| Finding | Action |
|---|---|
| AA has it under a different spelling | **Write an alias** (step 3). |
| AA has the model but not at this effort level (e.g. LMArena has `(Max)`, AA has base/`low`/`medium`) | **Leave it.** Inheriting another level's numbers would be worse than a visible gap. |
| AA does not have it at all | **Leave it.** Nothing to join. |

**3. Write the alias** — in Django admin (`ModelAlias`), or via the shell:

```python
ModelAlias.objects.create(
    source="artificial_analysis",
    category="agent",
    raw_name="<the AA name or slug that did not resolve>",
    canonical_key="<the LMArena agent model_key it should join>",
    note="AA spells it differently; verified against artificialanalysis.ai on 2026-09-11",
)
```

Fields: `source` is which side the alias belongs to, `raw_name` is the AA name or
slug that failed, `canonical_key` is the `agent` key from the report's `model_key`
column, and `note` is for the next reviewer.

**4. Apply it** — an alias is consumed by the match ladder, which runs during a
refresh:

```bash
uv run python manage.py refresh_leaderboard --source=artificial_analysis
```

Costs 4 AA requests against the 100/24 h quota. Otherwise it takes effect at the
next scheduled refresh (twice daily).

**An alias does not take effect on the next HTTP request.** This is deliberate:
the match is a stored fact that `/overview/`, `/models/{key}/` and `/unmatched/`
all read, so they cannot disagree with each other. See
[implementation.md](implementation.md#1-alias-promotion-takes-a-refresh-not-a-request).

**5. Confirm the fix.** The record disappears from both surfaces, because the
ledger is rebuilt per run rather than appended to:

```bash
uv run python manage.py report_unmatched --reason=no_aa_match    # one fewer row
curl 'localhost:8000/api/v1/leaderboard/models/<key>/'           # 404 -> 200
```

The old record is not deleted — it goes `is_current: false`, visible with
`--all`. That is what makes "when did this change, and did anyone decide it
should?" answerable later.

---

## Why the ledger is shaped this way

* **Current state, not an append-only log.** One row per
  `(source, category, reason, model_key)`, upserted each run with an
  `occurrences` counter. An append-only log would grow without bound and make
  "what is still broken?" require a scan.
* **Never deleted.** A record that stops recurring is flagged
  `is_current: false`. The history of a decision stays inspectable.
* **Rebuilt per run, so fixes clear themselves.** A record whose problem is
  resolved retires on the next refresh with no manual step — including when the
  fix was an alias.
* **Reason-scoped ownership.** Two phases write LMArena-sourced rows (the
  LMArena refresh writes `not_in_agent_set`; the AA refresh writes `no_aa_match`,
  because only it can know that fact). Each ledger closes only the reasons it
  owns, so neither can retire the other's fresh rows. Without that scope the
  report would silently lose a whole population — pinned by
  `test_the_two_ledgers_do_not_close_each_others_rows`.

---

## Reading the report from the frontend

The same data over HTTP, with filtering and pagination — see
[api.md](api.md#7-get-unmatched--the-review-queue). The useful calls:

```
# badge a "needs review" count
GET /unmatched/?reason=no_aa_match

# the AA side of the same review
GET /unmatched/?source=artificial_analysis&reason=no_lmarena_match

# everything that has persisted across several refreshes
GET /unmatched/?ordering=-occurrences

# what changed: hide the resolved ones
GET /unmatched/?current=true
```

`/metadata/`'s `counts.unmatched_records` gives the size of the whole queue in
one call, so a badge needs no page fetch.
