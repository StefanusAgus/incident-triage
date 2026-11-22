"""Ingest/detail API checks with an isolated dataset and file-backed SQLite DB."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

import app.ingest as ingest_module
from app.config import Settings
from app.main import create_app
from app.schemas import IncidentRecord

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "incidents.json"


@pytest.fixture
def ingest_client(tmp_path: Path):
    source = tmp_path / "incidents.json"
    shutil.copyfile(DATA_PATH, source)
    app = create_app(Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/incidents.db",
        data_path=source,
    ))
    with TestClient(app) as client:
        yield client, app, source


def storage_counts(app: FastAPI) -> tuple[int, int, int]:
    with app.state.engine.connect() as connection:
        incidents = connection.exec_driver_sql("SELECT count(*) FROM incidents").scalar_one()
        total, distinct = connection.exec_driver_sql(
            "SELECT count(*), count(DISTINCT incident_id) FROM incident_fts"
        ).one()
        return incidents, total, distinct


def fts_snapshot(app: FastAPI) -> list[tuple]:
    with app.state.engine.connect() as connection:
        return [tuple(row) for row in connection.exec_driver_sql(
            "SELECT incident_id, title, description, resolution_summary, tags "
            "FROM incident_fts ORDER BY incident_id"
        )]


def test_first_ingest_inserts_300_second_skips_and_details_are_complete(ingest_client) -> None:
    client, app, source = ingest_client
    first = json.loads(source.read_text(encoding="utf-8"))[0]
    response = client.post("/ingest")
    assert response.status_code == 200
    assert response.json() == {"ingested": 300, "skipped": 0, "updated": 0}
    before = fts_snapshot(app)
    response = client.post("/ingest")
    assert response.status_code == 200
    assert response.json() == {"ingested": 0, "skipped": 300, "updated": 0}
    assert storage_counts(app) == (300, 300, 300)
    assert fts_snapshot(app) == before
    details = client.get(f"/incidents/{first['id']}")
    assert details.status_code == 200
    assert details.json() == IncidentRecord.model_validate(first).model_dump(mode="json")
    missing = client.get("/incidents/INC-UNKNOWN")
    assert missing.status_code == 404
    assert "INC-UNKNOWN" in missing.json()["detail"]


def test_one_changed_record_updates_details_and_all_fts_fields(ingest_client) -> None:
    client, app, source = ingest_client
    assert client.post("/ingest").status_code == 200
    records = json.loads(source.read_text(encoding="utf-8"))
    changed = records[0]
    old_title = changed["title"]
    changed.update(
        title="newtitlemarker", description="newdescriptionmarker",
        resolution_summary="newresolutionmarker", tags=["newtagmarker"],
        environment="stage", severity="SEV2",
    )
    source.write_text(json.dumps(records), encoding="utf-8")
    response = client.post("/ingest")
    assert response.status_code == 200
    assert response.json() == {"ingested": 0, "skipped": 299, "updated": 1}
    assert storage_counts(app) == (300, 300, 300)
    assert client.get(f"/incidents/{changed['id']}").json() == changed
    with app.state.engine.connect() as connection:
        for column, term in (
            ("title", "newtitlemarker"), ("description", "newdescriptionmarker"),
            ("resolution_summary", "newresolutionmarker"), ("tags", "newtagmarker"),
        ):
            ids = connection.exec_driver_sql(
                "SELECT incident_id FROM incident_fts WHERE incident_fts MATCH ?",
                (f"{column}:{term}",),
            ).scalars().all()
            assert ids == [changed["id"]]
        old_query = 'title:"' + old_title.replace('"', '""') + '"'
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM incident_fts WHERE incident_id = ? AND incident_fts MATCH ?",
            (changed["id"], old_query),
        ).scalar_one() == 0
    assert client.post("/ingest").json() == {"ingested": 0, "skipped": 300, "updated": 0}


@pytest.mark.parametrize("problem", ["invalid_record", "duplicate_id", "invalid_json"])
def test_invalid_dataset_writes_nothing(ingest_client, problem: str) -> None:
    client, app, source = ingest_client
    records = json.loads(source.read_text(encoding="utf-8"))
    if problem == "invalid_record":
        records[-1]["severity"] = "SEV5"
    elif problem == "duplicate_id":
        records[-1]["id"] = records[0]["id"]
    source.write_text("not JSON" if problem == "invalid_json" else json.dumps(records), encoding="utf-8")
    response = client.post("/ingest")
    assert response.status_code == 422
    assert response.json()["detail"]["errors"]
    assert storage_counts(app) == (0, 0, 0)


def test_missing_dataset_has_configuration_guidance(ingest_client) -> None:
    client, app, source = ingest_client
    app.state.settings.data_path = source.with_name("missing.json")
    response = client.post("/ingest")
    assert response.status_code == 500
    assert "DATA_PATH" in response.json()["detail"]
    assert storage_counts(app) == (0, 0, 0)


def test_fts_failure_rolls_back_incident_changes_and_index(ingest_client, monkeypatch) -> None:
    client, app, source = ingest_client
    assert client.post("/ingest").status_code == 200
    records = json.loads(source.read_text(encoding="utf-8"))
    original = client.get(f"/incidents/{records[0]['id']}").json()
    original_fts = fts_snapshot(app)
    records[0]["title"] = "changed before forced FTS failure"
    records.append({**records[0], "id": "INC-0301"})
    source.write_text(json.dumps(records), encoding="utf-8")
    real_replace = ingest_module.replace_fts_entry

    def fail_after_fts_write(session: Session, record: IncidentRecord) -> None:
        real_replace(session, record)
        if record.id == "INC-0301":
            raise OperationalError("forced FTS failure", {}, RuntimeError("test failure"))

    monkeypatch.setattr(ingest_module, "replace_fts_entry", fail_after_fts_write)
    response = client.post("/ingest")
    assert response.status_code == 503
    assert "rolled back" in response.json()["detail"]
    assert client.get(f"/incidents/{original['id']}").json() == original
    assert client.get("/incidents/INC-0301").status_code == 404
    assert storage_counts(app) == (300, 300, 300)
    assert fts_snapshot(app) == original_fts


def test_concurrent_ingests_keep_counts_and_fts_entries_consistent(ingest_client) -> None:
    _, app, source = ingest_client

    def ingest_once(_: int) -> dict[str, int]:
        with Session(app.state.engine) as session:
            return ingest_module.ingest_incidents(session, source).model_dump()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(ingest_once, range(2)))
    assert sorted(results, key=lambda result: result["ingested"]) == [
        {"ingested": 0, "skipped": 300, "updated": 0},
        {"ingested": 300, "skipped": 0, "updated": 0},
    ]
    assert storage_counts(app) == (300, 300, 300)
