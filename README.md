# Incident Triage

FastAPI incident ingestion, details, and keyword search API with validated
contracts and a SQLite/FTS5 store for `incident-triage-take-home.md`. Assist is pending.
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
`LLM_TIMEOUT_SECONDS` sets the future LLM call timeout. The scaffold needs no
API key and makes no LLM calls. `DATABASE_URL` selects the SQLite store, defaulting
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
it directly. Counts must be non-negative. Twelve incident families are cycled
evenly, with compatible services and matching symptoms/resolutions. The
dataset uses severity labels `SEV1`–`SEV4`. Repeated runs produce identical JSON.
The generator uses only Python's standard library and needs no database or key.

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
  --data-urlencode 'environment=dev' \
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
| Why does orders-api return 503 during a traffic spike? | INC-0085, INC-0241, INC-0013 | 199 |
| Why did orders-api return 503 after a configuration deployment? | INC-0134, INC-0206, INC-0002 | 229 |
| Why is service authentication failing after certificate expiry? | INC-0003, INC-0027, INC-0135 | 136 |
| What caused the queue backlog? | INC-0064, INC-0088, INC-0112 | 25 |
| Why are payment requests timing out? | INC-0030, INC-0150, INC-0162 | 115 |
| Why is storage full? | INC-0127, INC-0139, INC-0199 | 75 |
| Why are DNS lookups failing after maintenance? | INC-0101, INC-0173, INC-0197 | 140 |

Each question retrieved its expected incident family in the top three. Removing
stopwords reduced the queue question from 275 to 25 matches with the same top
IDs. OR matching can still produce broad hit counts for remaining common words;
these are keyword matches, not counts of incidents judged relevant by an LLM.

## Pending endpoint documentation

`POST /assist` is not implemented. Its curl example and grounding checks will
be added alongside the implementation. The minimum query/filter unit tests
are covered by the search tests. See
`TRADEOFFS.md` for status and `AI-NOTES.md` for validation.
