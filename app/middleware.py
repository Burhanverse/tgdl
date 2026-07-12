from __future__ import annotations

import logging
from .db import Job

log = logging.getLogger(__name__)


def is_job_owner(chat_id: int, job: Job) -> bool:
    """Verify if the job belongs to the current chat session to prevent information leaks."""
    return job.chat_id == chat_id
