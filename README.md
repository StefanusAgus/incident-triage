# Incident Triage

FastAPI service for ingesting and searching historical incidents, then using a
grounded OpenAI call to suggest relevant precedents, diagnostic checks, and a
customer-facing draft. A minimal Streamlit UI is included.

## Architecture

- `app/ingest.py`: validates the complete dataset and synchronizes SQLite/FTS5.
- `app/search.py`: shared BM25 retrieval used by both `/search` and `/assist`.
- `app/assist.py`: fixed retrieve-then-LLM workflow and grounding checks.
- `app/db/`: SQLModel tables, SQLite sessions, FTS5 SQL, and trace persistence.
- `app/observability.py`: correlation IDs and JSON stdout events.
- `ui/app.py`: thin Streamlit client; search and assist logic stay in FastAPI.

SQLite keeps setup small. FTS5 provides keyword search, not semantic search.
The assist workflow is fixed rather than agentic.

## Setup

Requirements: Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked
test -f .env || cp .env.example .env
```

Set `LLM_API_KEY` in `.env` before calling `/assist`. The verified local
configuration uses:

```dotenv
LLM_MODEL=gpt-6.1-sol
LLM_TIMEOUT_SECONDS=30
DATA_PATH=data/incidents.json
DATABASE_URL=sqlite:///./data/incidents.db
PORT=8000
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_API_KEY` | unset | Required only by `/assist` |
| `LLM_MODEL` | `gpt-6.1-sol` | OpenAI model name; set to `gpt-6.1-sol` for the verified configuration |
| `LLM_TIMEOUT_SECONDS` | `30` | Provider timeout |
| `LLM_MAX_RETRIES` | `2` | SDK retries, capped at 5 |
| `DATABASE_URL` | `sqlite:///./data/incidents.db` | SQLite database |
| `DATA_PATH` | `data/incidents.json` | Ingest source |
| `PORT` | `8000` | FastAPI port |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Backend used by Streamlit |

## Run FastAPI

```bash
uv run python -m app.main
```

Useful URLs:

- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

## Generate and ingest data

The repository includes 300 deterministic incidents generated with seed 42.
Regenerate the default dataset or choose another assignment-valid size:

```bash
uv run python data/generate_data.py
uv run python data/generate_data.py --num-sample 200
```

With FastAPI running, ingest twice to verify idempotency:

```bash
curl -X POST http://127.0.0.1:8000/ingest
curl -X POST http://127.0.0.1:8000/ingest
```

For the bundled dataset and an empty database, the first response reports 300
ingested records. The second reports 300 skipped records. Changed IDs are
updated, and incident/FTS changes commit in one transaction.

## Search and incident details

```bash
curl --get http://127.0.0.1:8000/search \
  --data-urlencode 'q=database connection HTTP 503' \
  --data-urlencode 'environment=prod' \
  --data-urlencode 'service=inventory-api' \
  --data-urlencode 'severity=SEV3' \
  --data-urlencode 'tags=database' \
  --data-urlencode 'tags=connection-pool' \
  --data-urlencode 'limit=10'

curl http://127.0.0.1:8000/incidents/INC-0001
```

Search uses FTS5 BM25 with a stronger title weight. Filters combine with AND;
repeated tags require every exact, case-sensitive tag. Results sort by ascending
BM25 score, default to 10, and are capped at 50. `total` is calculated before
the limit. Punctuation is treated as plain input rather than raw FTS syntax.

## Assist

```bash
curl -X POST http://127.0.0.1:8000/assist \
  -H 'Content-Type: application/json' \
  -H 'X-Correlation-ID: demo-assist-001' \
  -d '{
    "question": "Why is inventory-api returning HTTP 503 during traffic spikes?",
    "environment": "prod",
    "service": "inventory-api",
    "severity": "SEV3",
    "tags": ["database", "connection-pool"]
  }'
```

`/assist` retrieves up to 10 candidates through the same `search_incidents`
function as `/search`, then makes one structured OpenAI Responses API call.
Responses use `answered`, `insufficient_evidence`, or `out_of_scope` and include
relevant IDs, reasons, source excerpts, proposed next steps, a customer draft,
and clarifying questions when needed.

The OpenAI client is created lazily on the first assist request, reused for
later requests in the same application process, and closed during shutdown.
Other endpoints therefore remain usable without an API key.

The backend rejects IDs outside the retrieved candidates and excerpts not found
in the cited record. Missing keys return 503; provider or invalid-output errors
return 502 with actionable guidance and the correlation ID.

## Observability

Every request accepts or generates `X-Correlation-ID`, returns it in the response
header, and emits compact JSON events to stdout. Assist events include search
input/output, top IDs, model timing/usage, final output, and selected IDs.

```bash
curl http://127.0.0.1:8000/debug/trace/demo-assist-001
```

The debug endpoint reads SQLite-backed events and assist chat history. The most
recent 100 events per ID are retained; rows and chat history have no automatic
cleanup. The endpoint is unauthenticated and may expose questions/model output,
so restrict or disable it before public deployment.

## Streamlit UI

Keep FastAPI running, then start Streamlit in another Bash terminal:

```bash
uv run streamlit run ui/app.py
```

Open http://localhost:8501. To use another backend:

```bash
API_BASE_URL=http://api-host:8000 uv run streamlit run ui/app.py
```

The UI keeps the latest result and trace in session state. Refresh trace calls
only the debug endpoint; Clear resets the form and saved UI state.

## Tests

```bash
uv run pytest
```

Focused suites:

```bash
uv run pytest tests/test_search.py
uv run pytest tests/test_assist.py
uv run pytest tests/test_ui.py
```

Tests use isolated databases and mocked provider calls. Search tests cover query
construction, combined filters, exact tags, ranking, limits, and punctuation.
Assist tests cover invalid citations/excerpts, empty evidence, status handling,
timeouts, missing configuration, and correlated traces.

## Troubleshooting

- **`LLM_API_KEY is not configured`**: set `LLM_API_KEY` and `LLM_MODEL` in
  `.env`, then restart FastAPI.
- **Authentication/model access error**: verify the key, project permissions,
  configured model, and model availability.
- **Timeout**: increase `LLM_TIMEOUT_SECONDS` within the allowed range or retry.
- **No search results**: ingest first and use concrete technical keywords.
- **FTS5 unavailable**: use a Python SQLite build compiled with FTS5 support.
- **Trace 404**: use the correlation ID returned by the request; traces are
  stored only after that request completes.
- **UI cannot connect**: confirm FastAPI is running and `API_BASE_URL` is correct.

## Known limitations

- Keyword retrieval has no semantic matching and broad OR queries can return
  weak candidates; the LLM must still reject irrelevant evidence.
- SQLite is suitable for this take-home, not high-write multi-instance tracing.
- Trace/chat retention has no cleanup policy or authentication.
- No schema migration framework is included; startup creates missing tables.
