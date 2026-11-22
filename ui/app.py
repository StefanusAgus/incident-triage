"""Minimal Streamlit client for the incident-triage assist workflow."""

import os
from typing import Any
from uuid import uuid4

import httpx
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ASSIST_TIMEOUT_SECONDS = 60.0
TRACE_TIMEOUT_SECONDS = 10.0
STATE_DEFAULTS = {
    "assist_result": None,
    "assist_error": None,
    "trace": None,
    "trace_error": None,
    "correlation_id": None,
    "question_input": "",
    "environment_input": "",
    "service_input": "",
    "severity_input": "",
    "tags_input": "",
}


def initialize_state() -> None:
    for key, value in STATE_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_state() -> None:
    for key, value in STATE_DEFAULTS.items():
        st.session_state[key] = value


def parse_tags(value: str) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in value.split(",") if tag.strip()))


def build_payload(
    question: str,
    environment: str,
    service: str,
    severity: str,
    tags: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question.strip(),
        "tags": parse_tags(tags),
    }
    for name, value in (
        ("environment", environment),
        ("service", service),
        ("severity", severity),
    ):
        if value.strip():
            payload[name] = value.strip()
    return payload


def api_error_message(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, dict):
        detail = detail.get("message", detail)
    return f"Backend returned HTTP {response.status_code}: {detail}"


def fetch_trace(correlation_id: str) -> None:
    try:
        response = httpx.get(
            f"{API_BASE_URL}/debug/trace/{correlation_id}",
            timeout=TRACE_TIMEOUT_SECONDS,
        )
        if response.is_error:
            st.session_state.trace = None
            st.session_state.trace_error = api_error_message(response)
            return
        st.session_state.trace = response.json()
        st.session_state.trace_error = None
    except httpx.TimeoutException:
        st.session_state.trace_error = (
            "Trace request timed out. The assist result is still available; "
            "use Refresh trace to try again."
        )
    except httpx.RequestError as exc:
        st.session_state.trace_error = (
            f"Could not connect to the trace endpoint at {API_BASE_URL}: {exc}"
        )


def submit_assist(payload: dict[str, Any]) -> None:
    correlation_id = str(uuid4())
    st.session_state.correlation_id = correlation_id
    st.session_state.assist_result = None
    st.session_state.assist_error = None
    st.session_state.trace = None
    st.session_state.trace_error = None

    try:
        response = httpx.post(
            f"{API_BASE_URL}/assist",
            json=payload,
            headers={"X-Correlation-ID": correlation_id},
            timeout=ASSIST_TIMEOUT_SECONDS,
        )
        st.session_state.correlation_id = response.headers.get(
            "X-Correlation-ID", correlation_id,
        )
        if response.is_error:
            st.session_state.assist_error = api_error_message(response)
        else:
            st.session_state.assist_result = response.json()
    except httpx.TimeoutException:
        st.session_state.assist_error = (
            "The assist request timed out. Check the FastAPI and OpenAI timeout "
            "settings, then retry."
        )
    except httpx.RequestError as exc:
        st.session_state.assist_error = (
            f"Could not connect to the FastAPI backend at {API_BASE_URL}: {exc}"
        )

    fetch_trace(st.session_state.correlation_id)


def render_result() -> None:
    result = st.session_state.assist_result
    if st.session_state.assist_error:
        st.error(st.session_state.assist_error)
    if result is None:
        return

    st.subheader("Assist result")
    st.write(f"**Response status:** `{result['status']}`")

    st.markdown("#### Relevant incidents")
    incidents = result.get("relevant_incidents", [])
    if not incidents:
        st.write("No relevant historical incidents were selected.")
    for incident in incidents:
        st.markdown(f"**{incident['incident_id']}** — {incident['reason']}")
        for excerpt in incident.get("supporting_excerpts", []):
            st.markdown(f"> {excerpt}")

    st.markdown("#### Next steps")
    for step in result.get("next_steps", []):
        st.markdown(f"- {step}")

    questions = result.get("targeted_questions", [])
    st.markdown("#### Clarifying questions")
    if questions:
        for question in questions:
            st.markdown(f"- {question}")
    else:
        st.write("None requested.")

    st.markdown("#### Customer-facing draft")
    st.info(result["customer_facing_draft"])


def render_trace_event(position: int, event: dict[str, Any]) -> None:
    step = event.get("step", "unknown")
    st.markdown(f"**{position}. `{step}`**")
    if step == "tool:search" and event.get("phase") == "input":
        st.write("Query:", event.get("query"))
        st.write("Filters:", event.get("filters", {}))
    elif step == "tool:search" and event.get("phase") == "output":
        st.write("Hit count:", event.get("hit_count", 0))
        st.write("Top IDs:", event.get("top_ids", []))
    elif step == "assist:selected_incidents":
        st.write("Selected IDs:", event.get("selected_ids", []))
    elif step == "assist:model":
        st.write(
            "Model:", event.get("model"),
            "Duration (ms):", event.get("duration_ms"),
            "Usage:", event.get("usage", {}),
        )
    elif step == "assist:error":
        st.write("Failed step:", event.get("failed_step"))


def render_trace() -> None:
    st.subheader("Observability trace")
    correlation_id = st.session_state.correlation_id
    st.write(f"**Correlation ID:** `{correlation_id or 'Not submitted'}`")

    if st.button("Refresh trace", disabled=not correlation_id):
        fetch_trace(correlation_id)

    if st.session_state.trace_error:
        st.warning(st.session_state.trace_error)

    trace = st.session_state.trace
    if trace is None:
        return
    for position, event in enumerate(trace.get("events", []), start=1):
        render_trace_event(position, event)
    with st.expander("Raw trace JSON", expanded=False):
        st.json(trace)


def main() -> None:
    st.set_page_config(page_title="Incident Triage", page_icon="🚨")
    initialize_state()

    st.title("Incident Triage")
    st.caption(f"FastAPI backend: {API_BASE_URL}")
    if st.button("Clear"):
        clear_state()
        st.rerun()

    with st.form("assist-form"):
        question = st.text_area(
            "Question", key="question_input",
            placeholder="What symptoms are you seeing?",
        )
        environment = st.selectbox(
            "Environment", ["", "dev", "qa", "stage", "prod"],
            key="environment_input",
        )
        service = st.text_input("Service", key="service_input")
        severity = st.selectbox(
            "Severity", ["", "SEV1", "SEV2", "SEV3", "SEV4"],
            key="severity_input",
        )
        tags = st.text_input(
            "Tags", key="tags_input", placeholder="database, connection-pool",
        )
        submitted = st.form_submit_button("Ask assist", type="primary")

    if submitted:
        payload = build_payload(question, environment, service, severity, tags)
        if not payload["question"]:
            st.session_state.assist_error = "Question is required."
        else:
            with st.spinner("Running incident assist..."):
                submit_assist(payload)

    render_result()
    render_trace()


if __name__ == "__main__":
    main()
