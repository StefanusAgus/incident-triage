"""Thin HTTP handlers for ingestion, incident details, and search."""

from typing import Annotated

import app.assist as assist_module
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from openai import OpenAI
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.database import get_correlation_trace, get_incident, get_session
from app.assist import (
    AssistConfigurationError,
    AssistOutputError,
    AssistProviderError,
    assist_incidents,
)
from app.ingest import ingest_incidents
from app.observability import is_valid_correlation_id, log_step
from app.schemas import (
    AssistRequest,
    AssistResponse,
    IncidentRecord,
    IngestResult,
    SearchParams,
    SearchResponse,
    TraceResponse,
)
from app.search import SearchQueryError, search_incidents

router = APIRouter()


def _error_detail(request: Request, message: str) -> dict[str, str]:
    return {
        "message": message,
        "correlation_id": request.state.correlation_id,
    }


def _add_chat_message(request: Request, role: str, content: object) -> None:
    request.state.chat_messages.append({"role": role, "content": content})


def _get_openai_client(request: Request) -> OpenAI:
    state = request.app.state
    if state.openai_client is None:
        with state.openai_client_lock:
            if state.openai_client is None:
                state.openai_client = assist_module.create_openai_client(
                    state.settings,
                )
    return state.openai_client


@router.get("/debug/trace/{correlation_id}", response_model=TraceResponse)
def debug_trace(
    correlation_id: str, session: Session = Depends(get_session),
) -> TraceResponse:
    if not is_valid_correlation_id(correlation_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Correlation ID must contain only letters, numbers, '.', '_', "
                "or '-' and be at most 128 characters."
            ),
        )
    trace = get_correlation_trace(session, correlation_id)
    if trace is None:
        raise HTTPException(
            status_code=404,
            detail=f"No stored trace was found for correlation ID '{correlation_id}'.",
        )
    return TraceResponse(
        correlation_id=correlation_id,
        events=trace.events,
        chat_history=trace.chat_history,
    )


@router.post("/ingest", response_model=IngestResult)
def ingest(request: Request, session: Session = Depends(get_session)) -> IngestResult:
    try:
        return ingest_incidents(session, request.app.state.settings.data_path)
    except (OSError, UnicodeError) as exc:
        raise HTTPException(
            status_code=500,
            detail="Cannot read the incident dataset. Set DATA_PATH to a readable UTF-8 JSON file (default: data/incidents.json).",
        ) from exc
    except ValidationError as exc:
        issues = [
            {"location": list(error["loc"]), "message": error["msg"]}
            for error in exc.errors(include_input=False, include_url=False)
        ]
        raise HTTPException(status_code=422, detail={
            "message": "Invalid incident dataset. Fix DATA_PATH contents before retrying.",
            "errors": issues,
        }) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="Incident storage is unavailable. Check SQLite database access and retry; ingestion was rolled back.",
        ) from exc


@router.get("/incidents/{id}", response_model=IncidentRecord)
def incident_details(id: str, session: Session = Depends(get_session)) -> IncidentRecord:
    incident = get_incident(session, id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"Incident '{id}' was not found.")
    return IncidentRecord.model_validate(incident)


@router.get("/search", response_model=SearchResponse)
def search(
    params: Annotated[SearchParams, Query()], session: Session = Depends(get_session),
) -> SearchResponse:
    try:
        return search_incidents(session, params)
    except SearchQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/assist", response_model=AssistResponse)
def assist(
    body: AssistRequest, request: Request, session: Session = Depends(get_session),
) -> AssistResponse:
    _add_chat_message(request, "user", body.model_dump(mode="json"))
    try:
        client = _get_openai_client(request)
        result = assist_incidents(
            session, body, request.app.state.settings, client,
        )
        _add_chat_message(request, "assistant", result.model_dump(mode="json"))
        return result
    except AssistConfigurationError as exc:
        log_step(
            "assist:error",
            failed_step="configuration",
            error_type=type(exc).__name__,
            error_message=str(exc),
            model=request.app.state.settings.llm_model,
        )
        _add_chat_message(request, "assistant", {"error": str(exc)})
        raise HTTPException(
            status_code=503, detail=_error_detail(request, str(exc)),
        ) from exc
    except (AssistProviderError, AssistOutputError) as exc:
        _add_chat_message(request, "assistant", {"error": str(exc)})
        raise HTTPException(
            status_code=502, detail=_error_detail(request, str(exc)),
        ) from exc
    except SQLAlchemyError as exc:
        message = (
            "Incident search failed. Check SQLite database access and FTS5 "
            "initialization, then retry."
        )
        _add_chat_message(request, "assistant", {"error": message})
        raise HTTPException(
            status_code=503,
            detail=_error_detail(
                request,
                message,
            ),
        ) from exc
