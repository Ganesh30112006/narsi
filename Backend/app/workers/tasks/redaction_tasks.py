from __future__ import annotations

import uuid
from typing import Any

from celery import shared_task

from app.services.redaction_service import run_redaction


@shared_task(name="govpii.generate_redaction", bind=True, acks_late=True, max_retries=0)
def generate_redaction(self: Any, redaction_id: str) -> None:
    run_redaction(uuid.UUID(redaction_id))
