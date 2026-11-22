"""SQLite schema, FTS5, persistence, and session lifecycle checks."""

import json
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.config import Settings
from app.db.database import build_engine, get_session, initialize_database
from app.main import create_app
from app.db.models import Incident
from app.schemas import IncidentRecord


@pytest.fixture
def record() -> IncidentRecord:
    path = Path(__file__).resolve().parents[1] / "data" / "incidents.json"
    raw = json.loads(path.read_text(encoding="utf-8"))[0]
    # Exercise normalization and SQLite round trips using a non-UTC input.
    raw["created_at"] = "2026-01-22T22:50:25+08:00"
    return IncidentRecord.model_validate(raw)


def test_schema_initialization_is_repeatable_and_fts5_works(tmp_path: Path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path}/nested/incidents.db")
    try:
        initialize_database(engine)
        initialize_database(engine)
        assert "incidents" in inspect(engine).get_table_names()
        with engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM incidents").scalar_one() == 0
            assert connection.exec_driver_sql("SELECT count(*) FROM incident_fts").scalar_one() == 0
            connection.exec_driver_sql(
                "INSERT INTO incident_fts (incident_id, title, description, resolution_summary, tags) "
                "VALUES (?, ?, ?, ?, ?)",
                ("TEST-1", "capacity", "exhausted", "expanded", "storage"),
            )
            for column, term in (
                ("title", "capacity"), ("description", "exhausted"),
                ("resolution_summary", "expanded"), ("tags", "storage"),
            ):
                rows = connection.exec_driver_sql(
                    "SELECT incident_id, bm25(incident_fts) FROM incident_fts "
                    "WHERE incident_fts MATCH ?", (f"{column}:{term}",),
                ).all()
                assert len(rows) == 1 and rows[0][0] == "TEST-1"
            # An ordinary FTS table stores its content independently.
            schema = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name = 'incident_fts'"
            ).scalar_one()
            assert "content=" not in schema.lower().replace(" ", "")
    finally:
        engine.dispose()


def test_incident_round_trip_preserves_json_tags_and_utc(record: IncidentRecord) -> None:
    engine = build_engine("sqlite://")
    try:
        initialize_database(engine)
        with Session(engine) as session:
            session.add(Incident.model_validate(record.model_dump()))
            session.commit()
        with Session(engine) as session:
            loaded = session.get(Incident, record.id)
            assert IncidentRecord.model_validate(loaded) == record
        with engine.connect() as connection:
            row = connection.exec_driver_sql(
                "SELECT tags, json_type(tags), environment, severity FROM incidents"
            ).one()
            assert json.loads(row[0]) == record.tags
            assert row[1:] == ("array", record.environment.value, record.severity.value)
        with Session(engine) as session:
            session.add(Incident.model_validate(record.model_dump()))
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_request_sessions_are_separate_and_rollback_uncommitted_work(
    record: IncidentRecord,
) -> None:
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    sessions = []

    @app.get("/session-check")
    def session_check(session: Session = Depends(get_session)) -> dict[str, str]:
        sessions.append(session)
        session.add(Incident.model_validate(record.model_dump()))
        session.flush()
        return {"id": record.id}

    with TestClient(app) as client:
        assert client.get("/session-check").status_code == 200
        assert client.get("/session-check").status_code == 200
        assert sessions[0] is not sessions[1]
        with Session(app.state.engine) as session:
            assert session.exec(select(Incident)).all() == []
