"""Validate a configured dataset and synchronize incidents and FTS atomically."""

from pathlib import Path

from sqlmodel import Session

from app.db.database import get_incident, ingest_transaction, replace_fts_entry
from app.db.models import Incident
from app.schemas import IncidentDataset, IncidentRecord, IngestResult


def ingest_incidents(session: Session, data_path: Path) -> IngestResult:
    # Validate the entire file, including ID uniqueness, before opening a write
    # transaction. The request-scoped session must not already be in a transaction.
    dataset = IncidentDataset.model_validate_json(data_path.read_text(encoding="utf-8"))
    result = IngestResult()
    with ingest_transaction(session):
        for record in dataset.root:
            existing = get_incident(session, record.id)
            if existing is None:
                session.add(Incident.model_validate(record.model_dump()))
                result.ingested += 1
            elif IncidentRecord.model_validate(existing) == record:
                result.skipped += 1
                continue
            else:
                existing.sqlmodel_update(record.model_dump())
                session.add(existing)
                result.updated += 1
            replace_fts_entry(session, record)
    return result
