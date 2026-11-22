"""Correlation IDs and compact JSON step logs for the assist workflow."""

import json
import logging
import re
from uuid import uuid4

from app.constants import MAX_CORRELATION_ID_LENGTH

LOGGER = logging.getLogger("incident_triage")
LOGGER.setLevel(logging.INFO)
CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def resolve_correlation_id(value: str | None) -> str:
    if value is not None:
        value = value.strip()
        if (
            value
            and len(value) <= MAX_CORRELATION_ID_LENGTH
            and CORRELATION_ID_PATTERN.fullmatch(value)
        ):
            return value
    return str(uuid4())


def log_step(correlation_id: str, step: str, **summary: object) -> None:
    LOGGER.info(json.dumps(
        {"correlation_id": correlation_id, "step": step, **summary},
        ensure_ascii=False,
        separators=(",", ":"),
    ))
