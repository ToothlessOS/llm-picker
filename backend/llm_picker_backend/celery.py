"""Celery application.

The schedule lives in `settings.CELERY_BEAT_SCHEDULE` rather than in a separate
`beat_schedule` literal here, so that the twice-daily crontab is reviewable in
the same diff as every other configurable value and can be overridden per
environment.

`DatabaseScheduler` (also set in settings) materializes those entries into
`django_celery_beat` rows, which means an operator can disable a run or change
its interval from the Django admin without a deploy -- and the code-declared
schedule is re-applied on the next beat start.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "llm_picker_backend.settings")

app = Celery("llm_picker_backend")
app.config_from_object("django.conf:settings", namespace="CELERY")

# Picks up `leaderboard.tasks`, which is the only place `@shared_task` appears.
app.autodiscover_tasks()
