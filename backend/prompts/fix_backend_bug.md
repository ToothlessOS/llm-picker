The backend service have been deployed and run for several days, then the Artificial Analysis loading failed. I am suspecting the newly updated model data from AA reveal some previously undiscovered bugs in the backend. Here's the detailed error log:

2026-10-13 00:00:09,956 ERROR leaderboard.services.refresh Artificial Analysis refresh failed
Traceback (most recent call last):
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 359, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
sqlite3.IntegrityError: UNIQUE constraint failed: leaderboard_llmmodel.slug

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/app/leaderboard/services/refresh.py", line 498, in refresh_aa
    return _execute_aa(
        run,
    ...<3 lines>...
        agent_rows=agent_rows,
    )
  File "/app/leaderboard/services/refresh.py", line 642, in _execute_aa
    models_by_aa_id = store.upsert_aa_models(
        parsed,
    ...<3 lines>...
        stats=stats,
    )
  File "/app/leaderboard/persistence.py", line 240, in upsert_aa_models
    obj, outcome = _upsert(LLMModel, {"aa_id": record.aa_id}, values, synced_at=synced_at)
                   ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/leaderboard/persistence.py", line 179, in _upsert
    obj.save(update_fields=[*values.keys(), "last_synced_at"])
    ~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 874, in save
    self.save_base(
    ~~~~~~~~~~~~~~^
        using=using,
        ^^^^^^^^^^^^
    ...<2 lines>...
        update_fields=update_fields,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 966, in save_base
    updated = self._save_table(
        raw,
    ...<4 lines>...
        update_fields,
    )
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 1110, in _save_table
    results = self._do_update(
        base_qs,
    ...<5 lines>...
        returning_fields,
    )
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/base.py", line 1213, in _do_update
    return filtered._update(values, returning_fields)
           ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/query.py", line 1327, in _update
    return query.get_compiler(self.db).execute_returning_sql(returning_fields)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 2140, in execute_returning_sql
    row_count = self.execute_sql(ROW_COUNT)
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 2111, in execute_sql
    row_count = super().execute_sql(result_type)
  File "/app/.venv/lib/python3.13/site-packages/django/db/models/sql/compiler.py", line 1624, in execute_sql
    cursor.execute(sql, params)
    ~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 79, in execute
    return self._execute_with_wrappers(
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        sql, params, many=False, executor=self._execute
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 92, in _execute_with_wrappers
    return executor(sql, params, many, context)
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 100, in _execute
    with self.db.wrap_database_errors:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/utils.py", line 94, in __exit__
    raise dj_exc_value.with_traceback(traceback) from exc_value
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/utils.py", line 105, in _execute
    return self.cursor.execute(sql, params)
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "/app/.venv/lib/python3.13/site-packages/django/db/backends/sqlite3/base.py", line 359, in execute
    return super().execute(query, params)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
django.db.utils.IntegrityError: UNIQUE constraint failed: leaderboard_llmmodel.slug
[2026-10-13 00:00:09,971: INFO/ForkPoolWorker-4] Task leaderboard.refresh_all[a9d46634-347c-457b-a290-6907e3aa6188] succeeded in 9.953802639618516s: {'lmarena': {'id': 101, 'source': 'lmarena', 'status': 'success', 'started_at': '2026-10-13T00:00:00.031086+00:00', 'finished_at': '2026-10-13T00:00:07.931103+00:00', 'duration_ms': 7900, 'records_seen': 271, 'records_created': 0, 'records_updated': 0, 'records_deactivated': 0, 'records_failed': 0, 'records_deduplicated': 469, 'anomalies_recorded': 628, 'error_code': '', 'error_message': ''}, 'artificial_analysis': {'id': 102, 'source': 'artificial_analysis', 'status': 'failed', 'started_at': '2026-10-13T00:00:07.936714+00:00', 'finished_at': '2026-10-13T00:00:09.961686+00:00', 'duration_ms': 2024, 'records_seen': 0, 'records_created': 0, 'records_updated': 0, 'records_deactivated': 0, 'records_failed': 0, 'records_deduplicated': 0, 'anomalies_recorded': 0, 'error_code': 'unexpected_error', 'error_message': 'IntegrityError: UNIQUE constraint failed: leaderboard_llmmodel.slug'}}

Since it looks like a data problem, we should be anble to replicate in the local dev environment as well.