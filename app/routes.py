"""Thin HTTP handlers for ingestion, incident details, and search."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app.db.database import get_incident, get_session
from app.assist import (
    AssistConfigurationError,
    AssistOutputError,
    AssistProviderError,
    assist_incidents,
)
from app.ingest import ingest_incidents
from app.schemas import AssistRequest, AssistResponse, IncidentRecord, IngestResult, SearchParams, SearchResponse
from app.search import SearchQueryError, search_incidents

router = APIRouter()


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
    try:
        return assist_incidents(
            session, body, request.app.state.settings,
            correlation_id=request.state.correlation_id,
        )
    except AssistConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (AssistProviderError, AssistOutputError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
