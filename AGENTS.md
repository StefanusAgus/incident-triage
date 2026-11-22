# Working agreement

Use `incident-triage-take-home.md` as the assignment;

## Design

- Python, FastAPI, uv, SQLModel, Pydantic, and SQLite FTS5 with BM25 keyword
  ranking. Use the official OpenAI Python SDK with structured output and a model
  selected through settings. Use pytest and FastAPI's Swagger UI at `/docs`.
- SQLite avoids database setup but provides no semantic search. A fixed assist
  workflow avoids agent complexity: retrieve through the shared search path,
  log `tool:search`, then call the LLM. JSON logs avoid an observability service;
  Swagger UI defers a dedicated frontend.
- Keep `app/main.py` small. Separate `config.py`, `models.py` (persistence),
  `schemas.py` (API validation), `database.py`, `ingest.py`, `search.py`,
  `assist.py`, and `observability.py`. Keep tests in `tests/`.
- Store constants/static values in `app/constants.py`, environment-backed
  settings in `app/config.py`, and LLM instructions as a named multiline string
  in `app/prompts.py`. Never embed secrets or hardcode the runtime model.

## Required quality as features are implemented

- Supply 200–500 complete incidents with all assignment fields; include a fixed
  seed and generator if synthetic. Ingest must be idempotent and return counts.
- Search supports text and environment/service/severity/tags filters, capped
  top N results, snippets, and a total hit count. Details return full records.
- Assist uses the same search code as `/search`, cites retrieved IDs, explains
  3–5 relevant incidents when available, and returns next steps and a customer
  draft. Never invent details; when evidence is absent, say so and request more
  information. Validate structured output and citations against retrieved data.
- Validate inputs, cap sizes and result counts, set external-call timeouts,
  and return useful errors. LLM failures, including a missing key, must explain
  configuration and run steps without leaking secrets.
- Accept or generate a request correlation ID and include it in every log line.
  Use JSON logs; record search query/filters, hit count/top IDs, and selected IDs
  for assist. A trace endpoint is optional.
- Add at least two meaningful unit tests for query/filter logic and/or grounding
  guardrails when those features exist. README must provide exact startup,
  ingest, search, assist, and test commands with curl examples.

## Workflow and evidence

Implement only the requested step, run relevant checks, report actual results
and remaining issues, then stop before the next step. Do not build future
features merely because the assignment requires them eventually.
