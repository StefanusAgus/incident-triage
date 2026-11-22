"""Application smoke and debug-trace checks."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_and_swagger_are_available() -> None:
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert "/health" in schema.json()["paths"]
        assert "/debug/trace/{correlation_id}" in schema.json()["paths"]


def test_debug_trace_and_stdout_observability_message(capsys) -> None:
    app = create_app(Settings(_env_file=None, database_url="sqlite://"))
    with TestClient(app) as client:
        stdout_events = [
            json.loads(line)
            for line in capsys.readouterr().out.splitlines()
            if line.strip()
        ]
        ready = next(
            event for event in stdout_events
            if event["step"] == "observability:ready"
        )
        assert ready["correlation_id"] == "system"
        assert "X-Correlation-ID" in ready["message"]
        assert "/debug/trace/{correlation_id}" in ready["message"]

        response = client.get(
            "/health", headers={"X-Correlation-ID": "trace-route-test"},
        )
        assert response.status_code == 200

        trace = client.get("/debug/trace/trace-route-test")
        assert trace.status_code == 200
        assert trace.json()["correlation_id"] == "trace-route-test"
        assert [event["step"] for event in trace.json()["events"]] == [
            "request:start", "request:complete",
        ]
        assert all(
            event["correlation_id"] == "trace-route-test"
            for event in trace.json()["events"]
        )

        assert client.get("/debug/trace/unknown-trace-id").status_code == 404
        assert client.get("/debug/trace/bad$value").status_code == 422


def test_debug_trace_survives_application_restart(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path}/persistent-trace.db"
    first_app = create_app(Settings(_env_file=None, database_url=database_url))
    with TestClient(first_app) as client:
        response = client.get(
            "/health", headers={"X-Correlation-ID": "restart-trace-test"},
        )
        assert response.status_code == 200

    second_app = create_app(Settings(_env_file=None, database_url=database_url))
    with TestClient(second_app) as client:
        trace = client.get("/debug/trace/restart-trace-test")
        assert trace.status_code == 200
        assert [event["step"] for event in trace.json()["events"]] == [
            "request:start", "request:complete",
        ]
        assert trace.json()["chat_history"] == []
