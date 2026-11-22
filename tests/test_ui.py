"""Focused tests for the Streamlit client's request helpers."""

from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from ui.app import api_error_message, build_payload, parse_tags


def test_build_payload_omits_blank_filters_and_normalizes_tags() -> None:
    assert build_payload(
        "  Why is checkout timing out?  ", "prod", "  ", "SEV2",
        " payment, timeout, payment,  ",
    ) == {
        "question": "Why is checkout timing out?",
        "environment": "prod",
        "severity": "SEV2",
        "tags": ["payment", "timeout"],
    }


def test_parse_tags_handles_empty_input() -> None:
    assert parse_tags(" , , ") == []


def test_api_error_message_reads_correlation_aware_backend_error() -> None:
    response = httpx.Response(
        502,
        request=httpx.Request("POST", "http://backend/assist"),
        json={
            "detail": {
                "message": "The OpenAI request timed out.",
                "correlation_id": "test-id",
            },
        },
    )
    assert api_error_message(response) == (
        "Backend returned HTTP 502: The OpenAI request timed out."
    )


def test_streamlit_page_renders_without_calling_backend() -> None:
    app_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    app = AppTest.from_file(app_path).run()
    assert not app.exception
    assert app.title[0].value == "Incident Triage"
    assert app.text_area[0].label == "Question"
    assert {button.label for button in app.button} == {
        "Clear", "Ask assist", "Refresh trace",
    }


def test_refresh_trace_does_not_resubmit_assist(monkeypatch) -> None:
    calls = {"assist": 0, "trace": 0}

    def fake_post(url, **kwargs):
        calls["assist"] += 1
        correlation_id = kwargs["headers"]["X-Correlation-ID"]
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            headers={"X-Correlation-ID": correlation_id},
            json={
                "status": "answered",
                "relevant_incidents": [],
                "next_steps": ["Check current logs."],
                "customer_facing_draft": "We are investigating.",
                "explanation": "Test response.",
                "targeted_questions": [],
            },
        )

    def fake_get(url, **kwargs):
        calls["trace"] += 1
        correlation_id = url.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "correlation_id": correlation_id,
                "events": [{
                    "correlation_id": correlation_id,
                    "step": "assist:selected_incidents",
                    "selected_ids": [],
                }],
                "chat_history": [],
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    app_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    app = AppTest.from_file(app_path).run()
    app.text_area[0].set_value("Why is checkout timing out?")
    next(button for button in app.button if button.label == "Ask assist").click()
    app.run()
    assert calls == {"assist": 1, "trace": 1}

    next(button for button in app.button if button.label == "Refresh trace").click()
    app.run()
    assert calls == {"assist": 1, "trace": 2}
