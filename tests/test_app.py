"""Scaffold smoke check; incident quality tests are pending implementation."""

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
