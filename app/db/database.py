"""SQLite engine creation, schema initialization, and request-scoped sessions."""

from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine

from app.db.models import Incident

CREATE_INCIDENT_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS incident_fts USING fts5(
    incident_id UNINDEXED,
    title,
    description,
    resolution_summary,
    tags
)
"""


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
