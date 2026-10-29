"""Job dispatch: inline thread pool (default, no broker), Celery/RabbitMQ, or eager (tests)."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from app.core.config import TaskExecution, get_settings
from app.core.exceptions import DependencyUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)
JobKind = Literal["scan", "redaction", "report"]

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()
_maintenance_stop = threading.Event()
_maintenance_thread: threading.Thread | None = None

# Inline mode has no Celery beat, so the same maintenance runs on a timer inside the API process.
MAINTENANCE_INTERVALS = {
    "cleanup_temporary_files": 3600.0,
    "purge_expired_public_uploads": 900.0,
    "apply_retention_policy": 6 * 3600.0,
}


def _handler(kind: JobKind) -> Callable[[uuid.UUID], None]:
    if kind == "scan":
        from app.services.scan_service import run_scan

        return run_scan
    if kind == "redaction":
        from app.services.redaction_service import run_redaction

        return run_redaction
    from app.workers.tasks.report_tasks import regenerate_report

    return regenerate_report


def _inline_executor() -> ThreadPoolExecutor:
    global _executor
    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=get_settings().inline_worker_threads, thread_name_prefix="govpii-job"
            )
        return _executor


def _safe(kind: JobKind, job_id: uuid.UUID) -> None:
    try:
        _handler(kind)(job_id)
    except Exception:  # handlers record their own failures; this guards the pool thread
        logger.exception("job_crashed", extra={"kind": kind, "job_id": str(job_id)})


def submit(kind: JobKind, job_id: uuid.UUID) -> str | None:
    """Queues a job after its database row has been committed. Returns a task id when available."""
    mode = get_settings().task_execution
    if mode is TaskExecution.EAGER:
        _safe(kind, job_id)
        return None
    if mode is TaskExecution.INLINE:
        _inline_executor().submit(_safe, kind, job_id)
        return None
    from app.workers.celery_app import celery_app

    task_names = {
        "scan": "govpii.process_document_scan",
        "redaction": "govpii.generate_redaction",
        "report": "govpii.generate_report",
    }
    queues = {"scan": "scans", "redaction": "redactions", "report": "reports"}
    try:
        result = celery_app.send_task(
            task_names[kind],
            args=[str(job_id)],
            queue=queues[kind],
            retry=True,
            retry_policy={"max_retries": 2, "interval_start": 0.5, "interval_step": 1},
        )
    except Exception as exc:  # broker unreachable (kombu raises several connection error types)
        logger.error("broker_unavailable", extra={"kind": kind, "reason": type(exc).__name__})
        raise DependencyUnavailableError("The processing queue is unavailable. Please try again shortly.") from exc
    return str(result.id)


def recover_interrupted() -> None:
    """Inline mode only. Jobs lived in the previous process, so after a restart nothing is running them."""
    from app.services.redaction_service import fail_interrupted_redactions
    from app.services.scan_service import recover_interrupted_scans

    queued = recover_interrupted_scans()
    failed_redactions = fail_interrupted_redactions()
    for scan_id in queued:
        submit("scan", scan_id)
    if queued or failed_redactions:
        logger.info("jobs_recovered", extra={"requeued_scans": len(queued), "failed_redactions": failed_redactions})


def _run_maintenance(name: str) -> None:
    from app.services.storage import cleanup_stale_workspaces
    from app.workers.tasks.report_tasks import apply_retention_policy, purge_expired_public_uploads

    try:
        if name == "cleanup_temporary_files":
            cleanup_stale_workspaces(get_settings())
        elif name == "purge_expired_public_uploads":
            purge_expired_public_uploads()
        else:
            apply_retention_policy()
    except Exception:  # keep the timer alive; the next run tries again
        logger.exception("maintenance_failed", extra={"task": name})


def _maintenance_loop() -> None:
    due = dict.fromkeys(MAINTENANCE_INTERVALS, 0.0)
    while not _maintenance_stop.is_set():
        now = time.monotonic()
        for name, interval in MAINTENANCE_INTERVALS.items():
            if now >= due[name]:
                _run_maintenance(name)
                due[name] = now + interval
        _maintenance_stop.wait(min(due.values()) - time.monotonic())


def start_maintenance() -> None:
    global _maintenance_thread
    if _maintenance_thread is not None:
        return
    _maintenance_stop.clear()
    _maintenance_thread = threading.Thread(target=_maintenance_loop, name="govpii-maintenance", daemon=True)
    _maintenance_thread.start()


def shutdown(wait: bool = True) -> None:
    """Graceful shutdown: running inline jobs finish; queued-but-unstarted jobs stay QUEUED and are queued again
    by recover_interrupted() on the next start."""
    global _executor, _maintenance_thread
    _maintenance_stop.set()
    if _maintenance_thread is not None:
        _maintenance_thread.join(timeout=5)
        _maintenance_thread = None
    with _executor_lock:
        if _executor is not None:
            _executor.shutdown(wait=wait, cancel_futures=True)
            _executor = None
