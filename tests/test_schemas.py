"""Validate the real dataset and reject malformed incident contracts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas import IncidentDataset, IncidentRecord

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "incidents.json"


def test_all_300_generated_records_validate() -> None:
    dataset = IncidentDataset.model_validate_json(DATA_PATH.read_text(encoding="utf-8"))
    assert len(dataset.root) == 300
    assert len({record.id for record in dataset.root}) == 300
    assert all(record.created_at.utcoffset().total_seconds() == 0 for record in dataset.root)


@pytest.mark.parametrize("field,value", [
    ("environment", "production"),
    ("severity", "SEV5"),
    ("tags", "database,tls"),
    ("tags", ["database", " "]),
    ("created_at", "2026-01-01T12:00:00"),
    ("title", " "),
    ("unexpected", "field"),
])
def test_invalid_incident_is_rejected(field: str, value: object) -> None:
    record = json.loads(DATA_PATH.read_text(encoding="utf-8"))[0]
    record[field] = value
    with pytest.raises(ValidationError):
        IncidentRecord.model_validate(record)


@pytest.mark.parametrize("field", [
    "id", "created_at", "environment", "service", "severity", "title",
    "description", "resolution_summary", "tags",
])
def test_every_incident_field_is_required(field: str) -> None:
    record = json.loads(DATA_PATH.read_text(encoding="utf-8"))[0]
    del record[field]
    with pytest.raises(ValidationError):
        IncidentRecord.model_validate(record)
