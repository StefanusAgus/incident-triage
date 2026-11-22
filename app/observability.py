"""Correlation IDs and compact JSON step logs for the assist workflow."""

import json
import logging
import re
from contextvars import ContextVar, Token
from uuid import uuid4

from app.constants import MAX_CORRELATION_ID_LENGTH

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
CORRELATION_ID_CONTEXT: ContextVar[str] = ContextVar(
    "correlation_id", default="system",
)
TRACE_EVENTS_CONTEXT: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "trace_events", default=None,
)


def configure_observability() -> None:
    """Prevent uncorrelated HTTP access lines; application events are JSON."""
    logging.getLogger("uvicorn.access").disabled = True


def _event(step: str, **summary: object) -> dict[str, object]:
    return {
        "correlation_id": CORRELATION_ID_CONTEXT.get(),
        "step": step,
        **summary,
    }


def _record_event(event: dict[str, object]) -> None:
    trace = TRACE_EVENTS_CONTEXT.get()
    if trace is not None:
        trace.append(event.copy())


def announce_observability() -> None:
    """Write one explicit JSON startup message to stdout."""
    event = _event(
        "observability:ready",
        message=(
            "JSON observability enabled. Send X-Correlation-ID and inspect "
            "GET /debug/trace/{correlation_id}; Uvicorn access logs are disabled."
        ),
    )
    print(json.dumps(event, separators=(",", ":")), flush=True)


def resolve_correlation_id(value: str | None) -> str:
    if value is not None and is_valid_correlation_id(value.strip()):
        return value.strip()
    return str(uuid4())


def is_valid_correlation_id(value: str) -> bool:
    return bool(
        value
        and len(value) <= MAX_CORRELATION_ID_LENGTH
        and CORRELATION_ID_PATTERN.fullmatch(value)
    )


def bind_correlation_id(correlation_id: str) -> Token[str]:
    return CORRELATION_ID_CONTEXT.set(correlation_id)


def reset_correlation_id(token: Token[str]) -> None:
    CORRELATION_ID_CONTEXT.reset(token)


def start_trace() -> Token[list[dict[str, object]] | None]:
    return TRACE_EVENTS_CONTEXT.set([])


def current_trace() -> list[dict[str, object]]:
    return [event.copy() for event in (TRACE_EVENTS_CONTEXT.get() or [])]


def reset_trace(token: Token[list[dict[str, object]] | None]) -> None:
    TRACE_EVENTS_CONTEXT.reset(token)


def log_step(step: str, **summary: object) -> None:
    event = _event(step, **summary)
    _record_event(event)
    print(json.dumps(event, separators=(",", ":")), flush=True)
