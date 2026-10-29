"""Celery application (RabbitMQ broker). Only used when TASK_EXECUTION=celery.

Run a worker:
    celery -A app.workers.celery_app worker -Q scans,ocr,redactions,reports,maintenance --concurrency 2 --loglevel INFO
Periodic maintenance (temp cleanup, retention):
    celery -A app.workers.celery_app beat --loglevel INFO
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()

celery_app = Celery("govpii", broker=settings.celery_broker_url or None, backend=settings.celery_result_backend or None)
celery_app.conf.update(
    task_ignore_result=not settings.celery_result_backend,  # state lives in the database
    task_acks_late=True,  # a crashed worker's job is redelivered…
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # …and one slow OCR job doesn't hold others hostage
    task_soft_time_limit=settings.max_processing_seconds + 30,
    task_time_limit=settings.max_processing_seconds + 90,
    task_default_queue="scans",
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "cleanup-temporary-files": {
            "task": "govpii.cleanup_temporary_files",
            "schedule": 3600.0,
            "options": {"queue": "maintenance"},
        },
        "purge-expired-public-uploads": {
            "task": "govpii.purge_expired_public_uploads",
            "schedule": 900.0,
            "options": {"queue": "maintenance"},
        },
        "apply-retention-policy": {
            "task": "govpii.apply_retention_policy",
            "schedule": 6 * 3600.0,
            "options": {"queue": "maintenance"},
        },
    },
)

import app.workers.tasks.redaction_tasks  # noqa: E402
import app.workers.tasks.report_tasks  # noqa: E402
import app.workers.tasks.scan_tasks  # noqa: E402,F401


@worker_process_init.connect
def _init_worker(**_: object) -> None:
    configure_logging(settings.log_level)
