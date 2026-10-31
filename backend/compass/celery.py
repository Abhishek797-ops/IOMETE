"""
Celery application.

Celery is optional: COMPASS is fully functional without a broker. When CELERY_ENABLED is
false, `CELERY_TASK_ALWAYS_EAGER` makes every task run inline, so the same code path is
exercised in development and in a containerised deployment with Redis.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "compass.settings.dev")

app = Celery("compass")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
