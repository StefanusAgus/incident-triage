"""Structured assist integration, grounding, and provider failure checks."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

import app.assist as assist_module
from app.config import Settings
from app.constants import ASSIST_CANDIDATE_LIMIT, ASSIST_MAX_OUTPUT_TOKENS
from app.db.models import CorrelationTrace
from app.main import create_app
from app.prompts import ASSIST_SYSTEM_PROMPT
from app.schemas import AssistResponse

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "incidents.json"


class FakeResponses:
    def __init__(self, output_factory):
        self.output_factory = output_factory
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.output_factory(kwargs)


class FakeClient:
    def __init__(self, output_factory):
        self.responses = FakeResponses(output_factory)


def completed(output: Any, *, items: list[Any] | None = None):
    return SimpleNamespace(
        status="completed", output_parsed=output, output=items or [],
        incomplete_details=None, error=None,
        usage=SimpleNamespace(input_tokens=80, output_tokens=40, total_tokens=120),
    )


@pytest.fixture
def assist_app(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/incidents.db",
        data_path=DATA_PATH,
        llm_api_key=SecretStr("test-key"),
        llm_model="test-model",
        llm_timeout_seconds=17,
        llm_max_retries=2,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.post("/ingest").json() == {"ingested": 300, "skipped": 0, "updated": 0}
        yield client, app, settings


def grounded_output_from_call(kwargs: dict[str, Any]) -> AssistResponse:
    evidence = json.loads(kwargs["input"])["retrieved_incidents"]
    first = evidence[0]
    return AssistResponse.model_validate({
        "status": "answered",
        "relevant_incidents": [{
            "incident_id": first["id"],
            "reason": f"A retrieved historical incident, {first['id']}, has matching symptoms.",
            "supporting_excerpts": [first["title"], first["tags"][0]],
        }],
        "next_steps": ["Check current logs for the same error signature."],
        "customer_facing_draft": "We are checking current telemetry against similar historical incidents.",
        "explanation": f"The available evidence supports comparison with {first['id']}.",
        "targeted_questions": [],
    })


def install_fake(monkeypatch, fake: FakeClient) -> None:
    monkeypatch.setattr(assist_module, "create_openai_client", lambda settings: fake)


def error_message(response) -> str:
    detail = response.json()["detail"]
    assert detail["correlation_id"] == response.headers["X-Correlation-ID"]
    return detail["message"]


def stdout_events(capsys, correlation_id: str) -> list[dict[str, Any]]:
    return [
        event
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
        for event in [json.loads(line)]
        if event["correlation_id"] == correlation_id
    ]


def test_assist_retrieves_full_records_and_makes_one_structured_call(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    fake = FakeClient(lambda kwargs: completed(grounded_output_from_call(kwargs)))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database connection pool HTTP 503"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert len(data["relevant_incidents"]) == 1
    assert len(fake.responses.calls) == 1
    call = fake.responses.calls[0]
    assert call["model"] == "test-model"
    assert call["instructions"] == ASSIST_SYSTEM_PROMPT
    assert call["text_format"] is AssistResponse
    assert call["max_output_tokens"] == ASSIST_MAX_OUTPUT_TOKENS
    assert call["store"] is False
    payload = json.loads(call["input"])
    assert 1 <= len(payload["retrieved_incidents"]) <= ASSIST_CANDIDATE_LIMIT
    assert set(payload["retrieved_incidents"][0]) == {
        "id", "created_at", "environment", "service", "severity", "title",
        "description", "resolution_summary", "tags",
    }


def test_assist_reuses_one_openai_client_across_requests(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    fake = FakeClient(lambda kwargs: completed(grounded_output_from_call(kwargs)))
    factory_calls = 0

    def create_client(settings):
        nonlocal factory_calls
        factory_calls += 1
        return fake

    monkeypatch.setattr(assist_module, "create_openai_client", create_client)
    for question in ("database connection pool", "HTTP 503 traffic spike"):
        response = client.post("/assist", json={"question": question})
        assert response.status_code == 200

    assert factory_calls == 1
    assert len(fake.responses.calls) == 2


def test_empty_evidence_still_calls_model_and_returns_targeted_questions(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app

    def output_factory(kwargs):
        assert json.loads(kwargs["input"])["retrieved_incidents"] == []
        return completed(AssistResponse.model_validate({
            "status": "insufficient_evidence",
            "relevant_incidents": [],
            "next_steps": ["Check the current service and error logs."],
            "customer_facing_draft": "We need a few more details before comparing this issue.",
            "explanation": "No relevant historical incidents were retrieved.",
            "targeted_questions": ["Which service is affected?", "What error message is visible?"],
        }))

    fake = FakeClient(output_factory)
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "quantum banana zxqv"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"
    assert len(fake.responses.calls) == 1


@pytest.mark.parametrize("invalid_kind", ["selected_id", "free_text_citation", "excerpt"])
def test_invalid_grounding_is_rejected(assist_app, monkeypatch, invalid_kind: str) -> None:
    client, _, _ = assist_app

    def output_factory(kwargs):
        output = grounded_output_from_call(kwargs).model_dump(mode="json")
        if invalid_kind == "selected_id":
            output["relevant_incidents"][0]["incident_id"] = "INC-9999"
        elif invalid_kind == "free_text_citation":
            output["customer_facing_draft"] = "A historical record INC-9999 confirms recovery."
        else:
            output["relevant_incidents"][0]["supporting_excerpts"] = ["This excerpt was invented."]
        return completed(AssistResponse.model_validate(output))

    fake = FakeClient(output_factory)
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database connection pool HTTP 503"})
    assert response.status_code == 502
    message = error_message(response)
    assert "retrieved evidence" in message or "does not occur" in message


def test_refusal_is_explicit(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    refusal = SimpleNamespace(type="refusal", refusal="I cannot process this request.")
    message = SimpleNamespace(type="message", status="completed", content=[refusal])
    fake = FakeClient(lambda kwargs: completed(None, items=[message]))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database timeout"})
    assert response.status_code == 502
    assert "refused" in error_message(response)


def test_incomplete_response_is_explicit(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    fake = FakeClient(lambda kwargs: SimpleNamespace(
        status="incomplete", output_parsed=None, output=[], error=None,
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    ))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database timeout"})
    assert response.status_code == 502
    assert "max_output_tokens" in error_message(response)


def test_missing_parsed_output_is_explicit(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    fake = FakeClient(lambda kwargs: completed(None))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database timeout"})
    assert response.status_code == 502
    assert "structured assist output" in error_message(response)


def test_invalid_structured_output_is_rejected(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    fake = FakeClient(lambda kwargs: completed({
        "status": "answered", "relevant_incidents": [], "explanation": "Invalid shape",
    }))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "database timeout"})
    assert response.status_code == 502
    assert "invalid structured assist output" in error_message(response)


def test_out_of_scope_status_declines_without_incidents(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app
    output = AssistResponse.model_validate({
        "status": "out_of_scope",
        "relevant_incidents": [],
        "next_steps": [],
        "customer_facing_draft": "I can only help with incident triage questions.",
        "explanation": "The request is unrelated to incident triage.",
        "targeted_questions": [],
    })
    fake = FakeClient(lambda kwargs: completed(output))
    install_fake(monkeypatch, fake)
    response = client.post("/assist", json={"question": "Write a wedding invitation"})
    assert response.status_code == 200
    assert response.json()["status"] == "out_of_scope"
    assert response.json()["relevant_incidents"] == []


def test_other_endpoints_work_without_key_and_assist_explains_configuration(tmp_path: Path) -> None:
    app = create_app(Settings(
        _env_file=None, database_url=f"sqlite:///{tmp_path}/incidents.db", data_path=DATA_PATH,
        llm_api_key=None,
    ))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/ingest").status_code == 200
        assert client.get("/search", params={"q": "database"}).status_code == 200
        response = client.post("/assist", json={"question": "database timeout"})
        assert response.status_code == 503
        message = error_message(response)
        assert "LLM_API_KEY" in message
        assert "LLM_MODEL" in message


def test_client_uses_explicit_timeout_and_bounded_sdk_retries(monkeypatch) -> None:
    captured = {}

    class CapturingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(assist_module, "OpenAI", CapturingOpenAI)
    settings = Settings(
        _env_file=None, llm_api_key=SecretStr("secret"), llm_timeout_seconds=19,
        llm_max_retries=3,
    )
    assist_module.create_openai_client(settings)
    assert captured == {"api_key": "secret", "timeout": 19, "max_retries": 3}


def test_assist_logs_search_steps_and_selected_ids_with_correlation_id(
    assist_app, monkeypatch, capsys,
) -> None:
    client, app, _ = assist_app
    fake = FakeClient(lambda kwargs: completed(grounded_output_from_call(kwargs)))
    install_fake(monkeypatch, fake)
    response = client.post(
        "/assist",
        json={"question": "database connection pool HTTP 503"},
        headers={"X-Correlation-ID": "test-correlation-123"},
    )
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "test-correlation-123"
    events = stdout_events(capsys, "test-correlation-123")
    assert [event["step"] for event in events] == [
        "request:start", "tool:search", "tool:search", "assist:model",
        "assist:output", "assist:selected_incidents", "request:complete",
    ]
    assert all(event["correlation_id"] == "test-correlation-123" for event in events)
    assert events[1]["phase"] == "input"
    assert events[2]["phase"] == "output"
    assert events[2]["hit_count"] >= len(events[2]["top_ids"])
    assert events[3]["model"] == "test-model"
    assert events[3]["duration_ms"] >= 0
    assert events[3]["usage"] == {
        "input_tokens": 80, "output_tokens": 40, "total_tokens": 120,
    }
    assert events[4]["output"] == response.json()
    assert events[5]["selected_ids"] == [response.json()["relevant_incidents"][0]["incident_id"]]
    assert events[6]["status_code"] == 200

    stored_response = client.get("/debug/trace/test-correlation-123")
    assert stored_response.status_code == 200
    stored = stored_response.json()
    assert stored["events"] == events
    assert stored["chat_history"] == [
        {
            "role": "user",
            "content": {
                "environment": None,
                "service": None,
                "severity": None,
                "tags": [],
                "question": "database connection pool HTTP 503",
            },
        },
        {"role": "assistant", "content": response.json()},
    ]
    with Session(app.state.engine) as session:
        assert session.get(CorrelationTrace, "test-correlation-123") is not None


def test_invalid_correlation_id_is_replaced(assist_app) -> None:
    client, _, _ = assist_app
    response = client.get("/health", headers={"X-Correlation-ID": "bad value with spaces"})
    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "bad value with spaces"


def test_timeout_is_actionable_and_logs_failed_model_step(
    assist_app, monkeypatch, capsys,
) -> None:
    client, _, _ = assist_app

    class ControlledTimeout(Exception):
        pass

    monkeypatch.setattr(assist_module, "APITimeoutError", ControlledTimeout)
    install_fake(monkeypatch, FakeClient(lambda kwargs: (_ for _ in ()).throw(
        ControlledTimeout("controlled timeout"),
    )))
    response = client.post(
        "/assist",
        json={"question": "database timeout"},
        headers={"X-Correlation-ID": "timeout-test"},
    )
    assert response.status_code == 502
    assert "LLM_TIMEOUT_SECONDS" in error_message(response)
    events = stdout_events(capsys, "timeout-test")
    failure = next(event for event in events if event["step"] == "assist:error")
    assert failure["failed_step"] == "model"
    assert failure["model"] == "test-model"
    assert failure["duration_ms"] >= 0
    assert all(event["correlation_id"] == "timeout-test" for event in events)


def test_model_access_failure_is_actionable(assist_app, monkeypatch) -> None:
    client, _, _ = assist_app

    class ControlledAccessError(Exception):
        pass

    monkeypatch.setattr(assist_module, "AuthenticationError", ControlledAccessError)
    install_fake(monkeypatch, FakeClient(lambda kwargs: (_ for _ in ()).throw(
        ControlledAccessError("do not expose this provider detail"),
    )))
    response = client.post("/assist", json={"question": "database timeout"})
    assert response.status_code == 502
    message = error_message(response)
    assert "authentication or model access failed" in message
    assert "do not expose" not in message


def test_search_failure_is_not_disguised_as_empty_evidence(
    assist_app, monkeypatch, capsys,
) -> None:
    client, _, _ = assist_app
    monkeypatch.setattr(
        assist_module,
        "search_incidents",
        lambda session, params: (_ for _ in ()).throw(SQLAlchemyError("controlled")),
    )
    response = client.post(
        "/assist",
        json={"question": "database timeout"},
        headers={"X-Correlation-ID": "search-failure-test"},
    )
    assert response.status_code == 503
    assert "Incident search failed" in error_message(response)
    events = stdout_events(capsys, "search-failure-test")
    failure = next(event for event in events if event["step"] == "assist:error")
    assert failure["failed_step"] == "search"
    assert all(event["correlation_id"] == "search-failure-test" for event in events)
