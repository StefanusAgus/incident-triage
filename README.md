# Incident Triage

Minimal scaffold for `incident-triage-take-home.md`. Incident features are not
implemented yet. The module boundaries and working rules are in `AGENTS.md`.

## Run (PowerShell)

Install uv and Python 3.14, then run from the repository root:

```powershell
uv sync --locked
Copy-Item .env.example .env
uv run python -m app.main
```

Copy the example only on first setup; preserve an existing `.env`.
The server defaults to http://127.0.0.1:8000. Swagger UI is at `/docs`, and the
schema is at `/openapi.json`. `PORT` changes the port for `python -m app.main`.

```powershell
curl.exe http://127.0.0.1:8000/health
uv run pytest
```

## Configuration

Settings load from environment variables or `.env` through `app/config.py`.
`LLM_API_KEY` is secret, `LLM_MODEL` selects the model, and
`LLM_TIMEOUT_SECONDS` sets the future LLM call timeout. The scaffold needs no
API key and makes no LLM calls. `DATABASE_URL` selects the future SQLite store;
startup does not create a database. `PORT` defaults to 8000.

## Pending endpoint documentation

`POST /ingest`, `GET /search`, `GET /incidents/{id}`, and `POST /assist` are not
implemented. Exact curl examples will be added alongside their actual schemas.
The dataset/generator and the assignment's two search/guardrail unit tests are
also pending. See `TRADEOFFS.md` for status and `AI-NOTES.md` for validation.
