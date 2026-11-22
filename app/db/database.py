"""SQLite engine creation, schema initialization, and request-scoped sessions."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request
from sqlalchemy.engine import Engine, RowMapping, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlalchemy import text
from sqlmodel import Session, create_engine

from app.db.models import Incident
from app.constants import SEARCH_SNIPPET_TOKENS, SEARCH_TITLE_WEIGHT
from app.schemas import IncidentFilters, IncidentRecord, SearchParams

CREATE_INCIDENT_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS incident_fts USING fts5(
    incident_id UNINDEXED,
    title,
    description,
    resolution_summary,
    tags
)
"""

DELETE_INCIDENT_FTS_SQL = "DELETE FROM incident_fts WHERE incident_id = :incident_id"
INSERT_INCIDENT_FTS_SQL = """
INSERT INTO incident_fts (incident_id, title, description, resolution_summary, tags)
VALUES (:incident_id, :title, :description, :resolution_summary, :tags)
"""

SEARCH_SOURCE_SQL = """
FROM incident_fts
JOIN incidents AS i ON i.id = incident_fts.incident_id
WHERE incident_fts MATCH :match_query
"""
SEARCH_RESULTS_SQL = """
SELECT i.id, i.title,
       snippet(incident_fts, 2, '', '', ' … ', :snippet_tokens) AS snippet,
       bm25(incident_fts, 0.0, :title_weight) AS score
"""
SEARCH_ORDER_SQL = "ORDER BY score ASC, i.id ASC LIMIT :limit"


def build_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("DATABASE_URL must use SQLite, e.g. sqlite:///./data/incidents.db")
    in_memory = url.database in (None, "", ":memory:")
    if not in_memory:
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        url,
        connect_args={"check_same_thread": False},
        **({"poolclass": StaticPool} if in_memory else {}),
    )


def initialize_database(engine: Engine) -> None:
    """Create missing tables without loading any incident records."""
    Incident.metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(CREATE_INCIDENT_FTS_SQL)
    except OperationalError as exc:
        if "no such module: fts5" in str(exc).lower():
            raise RuntimeError(
                "SQLite FTS5 is unavailable. Use a Python SQLite build with FTS5 support."
            ) from exc
        raise


def get_session(request: Request) -> Iterator[Session]:
    """One session per request; close and roll back uncommitted work on exit."""
    with Session(request.app.state.engine) as session:
        yield session


@contextmanager
def ingest_transaction(session: Session) -> Iterator[None]:
    """Serialize SQLite writers before reads so concurrent counts stay accurate."""
    with session.begin():
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        yield


def get_incident(session: Session, incident_id: str) -> Incident | None:
    return session.get(Incident, incident_id)


def replace_fts_entry(session: Session, record: IncidentRecord) -> None:
    """Replace an index entry on the caller's transaction without committing."""
    session.execute(text(DELETE_INCIDENT_FTS_SQL), {"incident_id": record.id})
    session.execute(text(INSERT_INCIDENT_FTS_SQL), {
        "incident_id": record.id,
        "title": record.title,
        "description": record.description,
        "resolution_summary": record.resolution_summary,
        "tags": json.dumps(record.tags, ensure_ascii=False),
    })


def build_search_filters(filters: IncidentFilters) -> tuple[str, dict[str, object]]:
    """Build predicates from trusted column names; bind every caller value."""
    clauses = []
    values: dict[str, object] = {}
    for field in ("environment", "service", "severity"):
        value = getattr(filters, field)
        if value is not None:
            clauses.append(f"i.{field} = :{field}")
            values[field] = value
    for index, tag in enumerate(dict.fromkeys(filters.tags)):
        parameter = f"tag_{index}"
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each(i.tags) AS tag "
            f"WHERE tag.value = :{parameter} COLLATE BINARY)"
        )
        values[parameter] = tag
    return (" AND " + " AND ".join(clauses) if clauses else ""), values


def query_search(
    session: Session, match_query: str, params: SearchParams,
) -> tuple[list[RowMapping], int]:
    predicates, values = build_search_filters(params)
    source = SEARCH_SOURCE_SQL + predicates
    values["match_query"] = match_query
    total = session.execute(text("SELECT count(*) " + source), values).scalar_one()
    rows = session.execute(
        text(SEARCH_RESULTS_SQL + source + " " + SEARCH_ORDER_SQL),
        {**values, "limit": params.limit, "title_weight": SEARCH_TITLE_WEIGHT,
         "snippet_tokens": SEARCH_SNIPPET_TOKENS},
    ).mappings().all()
    return list(rows), total
