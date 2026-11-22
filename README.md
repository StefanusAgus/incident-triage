# Incident Triage

Minimal scaffold for `incident-triage-take-home.md`. Incident features are not
implemented yet. The module boundaries and working rules are in `AGENTS.md`.

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
API key and makes no LLM calls. `DATABASE_URL` selects the future SQLite store;
startup does not create a database. `PORT` defaults to 8000.

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

## Pending endpoint documentation

`POST /ingest`, `GET /search`, `GET /incidents/{id}`, and `POST /assist` are not
implemented. Exact curl examples will be added alongside their actual schemas.
The assignment's two search/guardrail unit tests are also pending. See
`TRADEOFFS.md` for status and `AI-NOTES.md` for validation.
