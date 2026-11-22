"""Search safety, exact filters, ranking, totals, and sample-data demos."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import Settings
from app.constants import MAX_SNIPPET_LENGTH
from app.db.database import build_search_filters
from app.main import create_app
from app.schemas import IncidentFilters, SearchParams
from app.search import SearchQueryError, build_match_query, search_incidents
from data.generate_data import generate_incidents

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "incidents.json"


@pytest.fixture
def search_client(tmp_path: Path):
    base = {
        **generate_incidents(1)[0], "environment": "prod", "service": "orders-api",
        "severity": "SEV2", "description": "Diagnostic evidence collected.",
        "resolution_summary": "Applied a verified fix.", "tags": [],
    }
    variants = [
        {"id": "TEST-1", "title": "Database connection pool exhausted",
         "description": "Database connection timeout " + "x" * 500,
         "tags": ["database", "connection-pool", "database"]},
        {"id": "TEST-2", "title": "Database database database database outage",
         "tags": ["database-old", "connection-pool"]},
        {"id": "TEST-3", "title": "Database outage in stage", "environment": "stage",
         "tags": ["database", "connection-pool"]},
        {"id": "TEST-4", "title": "Database auth issue", "service": "auth-service",
         "tags": ["database", "connection-pool"]},
        {"id": "TEST-5", "title": "Database severity three", "severity": "SEV3",
         "tags": ["database", "connection-pool"]},
        {"id": "TEST-6", "title": "Database cache issue", "tags": ["database"]},
        {"id": "TEST-7", "title": "Certificate issue", "description": "Ordinary diagnostic details."},
        {"id": "TEST-8", "title": "Ordinary issue", "description": "Certificate diagnostic details."},
        {"id": "TEST-9", "title": "C++ orders-api returns 503",
         "description": "A C++ worker hit a dependency outage.", "service": "cpp-worker"},
    ]
    source = tmp_path / "incidents.json"
    source.write_text(json.dumps([{**base, **variant} for variant in variants]), encoding="utf-8")
    app = create_app(Settings(
        _env_file=None, database_url=f"sqlite:///{tmp_path}/incidents.db", data_path=source,
    ))
    with TestClient(app) as client:
        assert client.post("/ingest").status_code == 200
        yield client, app


@pytest.mark.parametrize("query,expected", [
    ("orders-api / 503?!", '"orders" OR "api" OR "503"'),
    ('database OR "tls" NEAR(foo)', '"database" OR "OR" OR "tls" OR "NEAR" OR "foo"'),
    ('title:database* NOT (certificate)', '"title" OR "database" OR "NOT" OR "certificate"'),
    ("C++ C++", '"C"'),
    ("WHAT caused THE queue backlog?", '"caused" OR "queue" OR "backlog"'),
    ("Why is TLS not working after HTTP-503?", '"TLS" OR "not" OR "working" OR "after" OR "HTTP" OR "503"'),
])
def test_query_builder_treats_words_as_quoted_literals(query: str, expected: str) -> None:
    assert build_match_query(query) == expected


@pytest.mark.parametrize("query", ["the", "WHY IS THE", "what?!", "?!"])
def test_query_builder_rejects_input_without_remaining_keywords(query: str) -> None:
    with pytest.raises(SearchQueryError, match="non-stopword keyword"):
        build_match_query(query)


def test_question_words_do_not_broaden_results(search_client) -> None:
    client, _ = search_client
    keywords = client.get("/search", params={"q": "database"})
    question = client.get("/search", params={"q": "WHAT IS THE database?"})
    assert keywords.status_code == question.status_code == 200
    assert question.json() == keywords.json()


def test_stopword_only_query_returns_useful_422(search_client) -> None:
    client, _ = search_client
    response = client.get("/search", params={"q": "What IS the?"})
    assert response.status_code == 422
    assert "non-stopword keyword" in response.json()["detail"]


def test_filter_builder_binds_values_instead_of_interpolating_them() -> None:
    service = "orders-api' OR 1=1 --"
    tag = "database'); DROP TABLE incidents; --"
    sql, values = build_search_filters(IncidentFilters(
        environment="prod", service=service, severity="SEV2", tags=[tag, tag],
    ))
    assert service not in sql and tag not in sql
    assert values == {"environment": "prod", "service": service, "severity": "SEV2", "tag_0": tag}


def test_combined_filters_apply_before_limit_and_require_all_tags(search_client) -> None:
    client, _ = search_client
    response = client.get("/search", params=[
        ("q", "database"), ("environment", "prod"), ("service", "orders-api"),
        ("severity", "SEV2"), ("tags", "database"), ("tags", "connection-pool"),
        ("limit", "1"),
    ])
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert [result["id"] for result in data["results"]] == ["TEST-1"]
    assert len(data["results"][0]["snippet"]) <= MAX_SNIPPET_LENGTH


def test_tags_are_exact_case_sensitive_and_do_not_duplicate_rows(search_client) -> None:
    client, _ = search_client
    data = client.get("/search", params={"q": "database", "tags": "database"}).json()
    ids = [result["id"] for result in data["results"]]
    assert data["total"] == 5
    assert len(ids) == len(set(ids)) == 5
    assert "TEST-2" not in ids
    assert client.get("/search", params={"q": "database", "tags": "Database"}).json()["total"] == 0
    assert client.get("/search", params=[
        ("q", "database"), ("tags", "database"), ("tags", "missing"),
    ]).json()["total"] == 0


def test_total_is_independent_of_limit_and_scores_sort_ascending(search_client) -> None:
    client, _ = search_client
    limited = client.get("/search", params={"q": "database", "limit": 2}).json()
    unlimited = client.get("/search", params={"q": "database", "limit": 50}).json()
    assert limited["total"] == unlimited["total"] == 6
    assert len(limited["results"]) == 2
    assert limited["results"] == unlimited["results"][:2]
    keys = [(result["score"], result["id"]) for result in unlimited["results"]]
    assert keys == sorted(keys)


def test_title_matches_rank_above_description_matches(search_client) -> None:
    client, _ = search_client
    results = client.get("/search", params={"q": "certificate"}).json()["results"]
    assert [result["id"] for result in results] == ["TEST-7", "TEST-8"]
    assert results[0]["score"] < results[1]["score"]


@pytest.mark.parametrize("query", ["C++", "orders-api / 503?!", '"503" (orders-api):*'])
def test_punctuation_is_safe_plain_text(search_client, query: str) -> None:
    client, _ = search_client
    response = client.get("/search", params={"q": query})
    assert response.status_code == 200
    assert [result["id"] for result in response.json()["results"]] == ["TEST-9"]


def test_injection_like_filters_do_not_bypass_filtering(search_client) -> None:
    client, _ = search_client
    response = client.get("/search", params={"q": "database", "service": "orders-api' OR 1=1 --"})
    assert response.status_code == 200
    assert response.json() == {"results": [], "total": 0}


@pytest.mark.parametrize("params", [
    {}, {"q": ""}, {"q": "  "}, {"q": "() : * !"}, {"q": "x" * 501},
    {"q": "database", "limit": 0}, {"q": "database", "limit": 51},
    {"q": "database", "environment": "production"},
    {"q": "database", "severity": "SEV5"}, {"q": "database", "tags": " "},
])
def test_invalid_search_input_returns_useful_validation_errors(search_client, params: dict) -> None:
    client, _ = search_client
    response = client.get("/search", params=params)
    assert response.status_code == 422
    assert response.json()["detail"]


def test_shared_search_function_matches_http_results(search_client) -> None:
    client, app = search_client
    params = SearchParams(q="database", environment="prod", tags=["database"], limit=2)
    with Session(app.state.engine) as session:
        shared = search_incidents(session, params).model_dump()
    response = client.get("/search", params={
        "q": "database", "environment": "prod", "tags": "database", "limit": 2,
    })
    assert response.json() == shared


@pytest.fixture(scope="module")
def sample_client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("search-demo")
    app = create_app(Settings(
        _env_file=None, database_url=f"sqlite:///{directory}/incidents.db", data_path=DATA_PATH,
    ))
    with TestClient(app) as client:
        assert client.post("/ingest").json()["ingested"] == 300
        yield client


def test_sample_data_default_limit_and_cap(sample_client) -> None:
    default = sample_client.get("/search", params={"q": "database"}).json()
    capped = sample_client.get("/search", params={"q": "database", "limit": 50}).json()
    assert default["total"] == capped["total"] > 50
    assert len(default["results"]) == 10
    assert len(capped["results"]) == 50


def test_queue_demo_ignores_filler_words(sample_client) -> None:
    question = sample_client.get("/search", params={"q": "What caused the queue backlog?"}).json()
    keywords = sample_client.get("/search", params={"q": "queue backlog"}).json()
    assert question["total"] == keywords["total"] == 25
    assert question["results"] == keywords["results"]


@pytest.mark.parametrize("question,tag", [
    ("Why does orders-api return 503 during a traffic spike?", "connection-pool"),
    ("Why did orders-api return 503 after a configuration deployment?", "configuration"),
    ("Why is service authentication failing after certificate expiry?", "certificate"),
    ("What caused the queue backlog?", "backlog"),
    ("Why are payment requests timing out?", "payment"),
    ("Why is storage full?", "storage"),
    ("Why are DNS lookups failing after maintenance?", "dns"),
])
def test_demo_questions_against_sample_data(sample_client, question: str, tag: str) -> None:
    response = sample_client.get("/search", params={"q": question, "limit": 3})
    assert response.status_code == 200
    data = response.json()
    ids = [result["id"] for result in data["results"]]
    records = {
        result["id"]: sample_client.get(f"/incidents/{result['id']}").json()
        for result in data["results"]
    }
    print(f"{question} -> total={data['total']}, top IDs={ids}")
    assert any(tag in record["tags"] for record in records.values())
