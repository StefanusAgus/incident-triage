"""Scaffold smoke check; incident quality tests are pending implementation."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_swagger_are_available() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.get("/docs").status_code == 200
        schema = client.get("/openapi.json")
        assert schema.status_code == 200
        assert "/health" in schema.json()["paths"]
