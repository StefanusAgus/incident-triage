"""Fixed workflow: shared retrieval, one structured OpenAI call, grounding checks."""

import json
import re
from typing import Any

from openai import APITimeoutError, OpenAI, OpenAIError
from pydantic import ValidationError
from sqlmodel import Session

from app.config import Settings
from app.constants import ASSIST_CANDIDATE_LIMIT, ASSIST_MAX_OUTPUT_TOKENS
from app.db.database import get_incidents
from app.prompts import ASSIST_SYSTEM_PROMPT
from app.observability import log_step
from app.schemas import AssistRequest, AssistResponse, IncidentRecord, SearchParams
from app.search import SearchQueryError, search_incidents

INCIDENT_ID_PATTERN = re.compile(r"\bINC-[A-Z0-9_-]+\b", re.IGNORECASE)


class AssistConfigurationError(RuntimeError):
    pass


class AssistProviderError(RuntimeError):
    pass


class AssistOutputError(RuntimeError):
    pass


def create_openai_client(settings: Settings) -> OpenAI:
    if settings.llm_api_key is None or not settings.llm_api_key.get_secret_value().strip():
        raise AssistConfigurationError(
            "LLM_API_KEY is not configured. Set LLM_API_KEY and LLM_MODEL, then restart the server."
        )
    return OpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def _find_refusal(response: Any) -> str | None:
    for item in getattr(response, "output", []):
        for content in getattr(item, "content", []):
            if getattr(content, "type", None) == "refusal":
                return getattr(content, "refusal", "The model refused the request.")
    return None


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _record_evidence(record: IncidentRecord) -> tuple[str, ...]:
    return (
        record.title,
        record.description,
        record.resolution_summary,
        *record.tags,
    )


def validate_grounding(output: AssistResponse, candidates: list[IncidentRecord]) -> None:
    candidates_by_id = {record.id: record for record in candidates}
    selected_ids = {item.incident_id for item in output.relevant_incidents}
    unknown_selected = selected_ids - candidates_by_id.keys()
    if unknown_selected:
        raise AssistOutputError(
            f"Model selected incident IDs outside retrieved evidence: {sorted(unknown_selected)}"
        )

    serialized = json.dumps(output.model_dump(mode="json"), ensure_ascii=False)
    cited_ids = {match.upper() for match in INCIDENT_ID_PATTERN.findall(serialized)}
    candidate_ids = {incident_id.upper() for incident_id in candidates_by_id}
    unknown_citations = cited_ids - candidate_ids
    if unknown_citations:
        raise AssistOutputError(
            f"Model cited incident IDs outside retrieved evidence: {sorted(unknown_citations)}"
        )

    for item in output.relevant_incidents:
        evidence = tuple(_normalize_text(value) for value in _record_evidence(candidates_by_id[item.incident_id]))
        for excerpt in item.supporting_excerpts:
            normalized_excerpt = _normalize_text(excerpt)
            if not any(normalized_excerpt in value for value in evidence):
                raise AssistOutputError(
                    f"Supporting excerpt for {item.incident_id} does not occur in that incident record."
                )


def assist_incidents(
    session: Session,
    request: AssistRequest,
    settings: Settings,
    client: Any | None = None,
    correlation_id: str = "unknown",
) -> AssistResponse:
    """Retrieve up to ten records, then make exactly one structured model call."""
    filters = request.model_dump(exclude={"question"})
    log_step(
        correlation_id,
        "tool:search",
        phase="input",
        query=request.question,
        filters=filters,
    )
    search_params = SearchParams(q=request.question, limit=ASSIST_CANDIDATE_LIMIT, **filters)
    search_total = 0
    try:
        search_response = search_incidents(session, search_params)
        ranked_ids = [result.id for result in search_response.results]
        search_total = search_response.total
    except SearchQueryError:
        ranked_ids = []

    candidates = [IncidentRecord.model_validate(record) for record in get_incidents(session, ranked_ids)]
    log_step(
        correlation_id,
        "tool:search",
        phase="output",
        hit_count=search_total,
        top_ids=ranked_ids,
    )
    model_input = json.dumps({
        "question": request.question,
        "filters": filters,
        "retrieved_incidents": [record.model_dump(mode="json") for record in candidates],
    }, ensure_ascii=False)

    runtime_client = client if client is not None else create_openai_client(settings)
    try:
        response = runtime_client.responses.parse(
            model=settings.llm_model,
            instructions=ASSIST_SYSTEM_PROMPT,
            input=model_input,
            text_format=AssistResponse,
            max_output_tokens=ASSIST_MAX_OUTPUT_TOKENS,
            store=False,
        )
    except APITimeoutError as exc:
        raise AssistProviderError(
            "The OpenAI request timed out after bounded retries. Check LLM_TIMEOUT_SECONDS and retry."
        ) from exc
    except (OpenAIError, ValidationError) as exc:
        raise AssistProviderError(
            "The OpenAI structured-output request failed. Check LLM_API_KEY, LLM_MODEL, and provider access."
        ) from exc

    refusal = _find_refusal(response)
    if refusal is not None:
        raise AssistProviderError(f"The model refused the assist request: {refusal}")
    response_status = getattr(response, "status", None)
    message_incomplete = any(
        getattr(item, "type", None) == "message" and getattr(item, "status", None) == "incomplete"
        for item in getattr(response, "output", [])
    )
    if response_status == "incomplete" or message_incomplete:
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown reason"
        raise AssistProviderError(f"The model response was incomplete: {reason}.")
    if response_status != "completed":
        error = getattr(response, "error", None)
        message = getattr(error, "message", None) or response_status or "unknown status"
        raise AssistProviderError(f"The model response did not complete: {message}.")
    output = getattr(response, "output_parsed", None)
    if output is None:
        raise AssistOutputError("The model did not return valid structured assist output.")
    if not isinstance(output, AssistResponse):
        try:
            output = AssistResponse.model_validate(output)
        except ValidationError as exc:
            raise AssistOutputError("The model returned invalid structured assist output.") from exc
    validate_grounding(output, candidates)
    log_step(
        correlation_id,
        "assist:selected_incidents",
        selected_ids=[item.incident_id for item in output.relevant_incidents],
    )
    return output
