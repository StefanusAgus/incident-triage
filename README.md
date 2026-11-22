# Incident Triage

FastAPI incident ingestion, details, keyword search, and grounded AI assist API
with validated contracts and a SQLite/FTS5 store for `incident-triage-take-home.md`.
The module boundaries and working rules are in `AGENTS.md`.

## Run (Bash)

Install uv and Python 3.14, then run from the repository root:

```bash
uv sync --locked
cp .env.example .env
uv run python -m app.main
```

Copy the example only on first setup; preserve an existing `.env`.
The server defaults to http://127.0.0.1:8000. Swagger UI is at `/docs`, and the
schema is at `/openapi.json`. `PORT` changes the port for `python -m app.main`.

```bash
curl http://127.0.0.1:8000/health
uv run pytest
```

## Configuration

Settings load from environment variables or `.env` through `app/config.py`.
`LLM_API_KEY` is secret, `LLM_MODEL` selects the model, and
`LLM_TIMEOUT_SECONDS` sets the OpenAI call timeout. `LLM_MAX_RETRIES` defaults
to 2 and is capped at 5; the official SDK applies bounded exponential backoff.
`POST /assist` requires `LLM_API_KEY` and access to `LLM_MODEL`. Startup, health,
ingest, details, and search remain usable without a key. `DATABASE_URL` selects the SQLite store, defaulting
to `sqlite:///./data/incidents.db`. Startup creates missing parent directories
and initializes empty tables. `PORT` defaults to 8000.
`DATA_PATH` selects the ingest source, defaulting to `data/incidents.json`.
Relative paths are resolved from the server's working directory; run from the
repository root.

## Generate synthetic data

```bash
uv run python data/generate_data.py
# Optional: choose a different sample count.
uv run python data/generate_data.py --num-sample 200
```

By default, this writes 300 incidents to `data/incidents.json`, using seed 42
and dates from January through June 2026. `--num-sample` overrides the count;
both `generate_incidents(num_sample=...)` and `main(num_sample=...)` also accept
it directly. Counts must be non-negative. Twelve families each contain three
paired symptom/cause/resolution scenarios and five relevant workload contexts.
Service/scenario/context combinations are shuffled with the seeded RNG and
sampled without replacement. At 300 records, each family contributes 25 records
and each scenario contributes 8 or 9. All 300 titles, descriptions, and
resolutions are distinct without relying on IDs, dates, or environments.

The current catalog supports 540 unique balanced samples, including the
assignment's 200–500 range. Larger requests fail clearly before overwriting the
output. The dataset uses severity labels `SEV1`–`SEV4`. Repeated runs produce
identical JSON, and requesting more records preserves the existing prefix.
The generator uses only Python's standard library and needs no database or key.
After regenerating, call `POST /ingest` again to refresh an existing database
and its FTS content; running the generator alone only replaces the JSON file.

## Data contracts and database

`app/schemas.py` defines `IncidentRecord` and `IncidentDataset`. Every incident
field is required; environments are dev/qa/stage/prod and severities are
SEV1–SEV4. Timestamps must include a timezone and are normalized to UTC. Tags
are arrays of non-empty strings, and unknown record fields are rejected.

`app/db/models.py` maps incidents to SQLModel, storing tags as a JSON array and
preserving UTC timestamps across SQLite round trips. `app/db/database.py` provides
engine creation, repeatable initialization, and a request-scoped session
dependency. Sessions close and roll back uncommitted work after each request.
Ingestion commits its batch explicitly.

Application startup creates the `incidents` table and an ordinary FTS5 table,
`incident_fts`, with searchable title, description, resolution_summary, and tags.
FTS content is independent of the incidents table. Startup does not ingest or
index records. SQLite must have FTS5 support; startup reports a
clear error if it is unavailable. Initialization creates tables, not migrations.

```bash
uv run pytest tests/test_schemas.py tests/test_database.py
```

These checks validate all 300 saved records and verify initialization, FTS5,
JSON tags, UTC persistence, and request-session isolation without modifying the
application database.

## Ingest and incident details

With the server running, use another Bash terminal:

```bash
curl -X POST http://127.0.0.1:8000/ingest
curl -X POST http://127.0.0.1:8000/ingest
curl http://127.0.0.1:8000/incidents/INC-0001
```

`POST /ingest` takes no body; it loads `DATA_PATH`. With the default 300-record
dataset and an empty database, the first response is
`{"ingested":300,"skipped":0,"updated":0}` and the second is
`{"ingested":0,"skipped":300,"updated":0}`. `ingested` counts newly inserted
IDs. Changed records count as `updated`; unchanged validated records count as
`skipped`. Comparisons use normalized records, including UTC timestamps.

The whole file is validated before writing; duplicate IDs are rejected.
Each batch updates incidents and FTS entries in one transaction. Changed index
entries are replaced, so repeated ingestion does not duplicate them. SQLite
writers are serialized before reading existing records to keep concurrent
counts accurate. Records absent from the source file are retained.

`GET /incidents/{id}` returns every incident field, with tags as an array and a
UTC timestamp, or HTTP 404 with the missing ID. Ingestion returns HTTP 422 for
invalid JSON/records, HTTP 500 with DATA_PATH guidance for unreadable files, and
HTTP 503 for storage failures after rollback.

```bash
uv run pytest tests/test_ingest.py
```

These tests use a temporary source file and isolated SQLite database. They
verify inserts/skips/updates, all FTS fields, full details/404, validation before
writes, rollback on FTS failure, and concurrent ingestion.

## Search

```bash
curl --get http://127.0.0.1:8000/search \
  --data-urlencode 'q=database connection timeouts' \
  --data-urlencode 'environment=prod' \
  --data-urlencode 'service=inventory-api' \
  --data-urlencode 'severity=SEV3' \
  --data-urlencode 'tags=database' \
  --data-urlencode 'tags=connection-pool' \
  --data-urlencode 'limit=10'

curl --get http://127.0.0.1:8000/search \
  --data-urlencode 'q=orders-api / 503?!'
```

`GET /search` requires `q`. It treats Unicode words/numbers as literal keywords,
removes common question words using `SEARCH_STOPWORDS` in `constants.py`
(case-insensitively), separates punctuation (including hyphens), and matches
any remaining keyword with OR. Technical/causal words such as "not", "out",
and "after" remain searchable.
Caller-supplied quotes, operators, prefixes, and column syntax are not exposed
as FTS syntax. There is no stemming or semantic matching.

Filters combine with AND. Environment/severity use the incident enums; service
and tags use exact, case-sensitive values after trimming surrounding whitespace.
Repeat `tags` to require all tags; commas are part of a tag, not separators.
Filtering happens before ranking and limiting. Exact tag checks use EXISTS,
so duplicate values in a record's tags do not duplicate hits.

The response has `results` (id, title, snippet, score) and `total`, the filtered
keyword hit count before the limit. Results use ascending FTS5 BM25 scores
(lower is better), with title weight 5 and other searchable fields weight 1.
Ties sort by incident ID. Description snippets are plain text capped at 240
characters. Results default to 10; `limit` must be between 1 and 50.

Missing, blank, punctuation-only, stopword-only, or over-500-character queries return HTTP
422 with validation details. Filters permit at most 10 tags and 100 characters
per service/tag value. The shared `search_incidents(session, SearchParams(...))`
function will also serve `/assist`; it contains no HTTP-specific behavior.

```bash
uv run pytest tests/test_search.py
```

No separate demo-question list was supplied. These representative questions
were tried against the default 300-record dataset, with `limit=3`:

| Question | Top incident IDs | Total keyword hits |
| --- | --- | --- |
| Why does orders-api return 503 during a traffic spike? | INC-0073, INC-0181, INC-0037 | 192 |
| Why did orders-api return 503 after a configuration deployment? | INC-0182, INC-0290, INC-0002 | 240 |
| Why is service authentication failing after certificate expiry? | INC-0219, INC-0111, INC-0003 | 147 |
| What caused the queue backlog? | INC-0172, INC-0244, INC-0028 | 25 |
| Why are payment requests timing out? | INC-0150, INC-0006, INC-0114 | 140 |
| Why is storage full? | INC-0223, INC-0007, INC-0043 | 34 |
| Why are DNS lookups failing after maintenance? | INC-0005, INC-0077, INC-0185 | 174 |

Each question retrieved its expected incident family in the top three. These
results were rerun after expanding the dataset's scenarios and contexts. OR
matching can still produce broad hit counts for remaining common words; these
are keyword matches, not counts of incidents judged relevant by an LLM.

## Assist

Set `LLM_API_KEY` and `LLM_MODEL` in `.env`, start the server, and ingest the
dataset. Then call:

```bash
curl -X POST http://127.0.0.1:8000/assist \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: demo-assist-001' \
  -d '{
    "question": "Why is orders-api returning HTTP 503 during traffic spikes?",
    "environment": "prod",
    "service": "orders-api",
    "severity": "SEV2",
    "tags": ["database", "connection-pool"]
  }'
```

Filters use the same semantics as `/search`. The fixed workflow retrieves up to
10 ranked IDs through `search_incidents`, loads their full records, and makes
exactly one OpenAI Responses API call with `AssistResponse` as the structured
Pydantic format. Even zero retrieved records are sent to the model.

The response status is `answered`, `insufficient_evidence`, or `out_of_scope`.
It contains selected incidents with reasons and short verbatim excerpts, proposed
next-step checks, a short customer-facing draft, an explanation, and targeted
questions when evidence is insufficient. Runtime instructions prefer 3–5
incidents when supported, allow fewer when evidence is limited, and forbid
padding selections.

The server rejects selected or text-cited IDs outside the retrieved candidates.
Every supporting excerpt must occur in the cited record's title, description,
resolution summary, or tags. Provider failures—including authentication/model
access, timeout, refusal, and incomplete responses—and invalid structured output
return HTTP 502. A missing key or search/storage failure returns HTTP 503 with
actionable guidance. Error bodies and response headers include the correlation
ID; provider details and stack traces remain in server-side diagnostics.

Every request accepts or generates `X-Correlation-ID` and echoes it in the
response. Supplied IDs may contain letters, numbers, `.`, `_`, and `-`, up to
128 characters; invalid values are replaced rather than written to logs. A
request-scoped context safely adds the ID to every application JSON event.
Uncorrelated Uvicorn access logs are disabled. Assist logs request start/end,
`tool:search` input/output, selected IDs, model, call duration, and token usage
when the provider supplies it. Failures record the failed step and safe provider
metadata without logging the API key. Every assist step, including the final
structured `assist:output`, is written as JSON to stdout.

Inspect a stored request trace:

```bash
curl http://127.0.0.1:8000/health \
  -H 'X-Correlation-ID: debug-demo-001'
curl http://127.0.0.1:8000/debug/trace/debug-demo-001
```

`GET /debug/trace/{correlation_id}` returns the JSON events currently retained
for that ID plus its assist chat history, or 404 when none are present. SQLite
stores one `correlation_traces` row per ID, with `events` and `chat_history` JSON
arrays. Reusing an ID appends new requests and assist exchanges. The latest 100
events per ID are retained; chat history is not currently pruned. Records survive
server restarts. Startup writes an `observability:ready` JSON message to stdout
with the header name and trace endpoint.

The debug route is intentionally basic and unauthenticated for this local
take-home application. Restrict or disable it before exposing the API publicly,
because traces include user questions and structured assist responses.

```bash
uv run pytest tests/test_assist.py
```

Tests mock the provider and cover the one-call contract, full/empty evidence,
all three statuses, invalid IDs and excerpts, invalid structured output,
refusal/incomplete responses, timeout/retry configuration, missing-key,
authentication/model access, search failure, and an end-to-end correlated log
trace. Coverage also verifies SQLite persistence across application restarts and
stored assist chat/output. No live OpenAI call was made during automated
verification; provide a valid key/model to exercise the runtime call.

## Streamlit UI

Configure `LLM_API_KEY` and `LLM_MODEL`, then run FastAPI from the repository
root in one Bash terminal:

```bash
uv sync --locked
uv run python -m app.main
```

Ingest the dataset once from a second terminal, then start Streamlit:

```bash
curl -X POST http://127.0.0.1:8000/ingest
uv run streamlit run ui/app.py
```

Streamlit opens the UI at http://localhost:8501. It calls the existing `/assist`
and `/debug/trace/{correlation_id}` endpoints and does not duplicate backend
retrieval or LLM logic. `API_BASE_URL` defaults to
`http://127.0.0.1:8000`; override it in Bash when the API runs elsewhere:

```bash
API_BASE_URL=http://api-host:8000 uv run streamlit run ui/app.py
```

Each submission generates a new correlation ID. The latest assist result and
trace remain in Streamlit session state across reruns. Refresh trace only calls
the debug endpoint; it does not resubmit the assist request. Clear removes the
saved result, trace, correlation ID, and form values.

## Remaining work

The core assignment endpoints are implemented. See `TRADEOFFS.md` for known
limits and `AI-NOTES.md` for actual validation evidence.
