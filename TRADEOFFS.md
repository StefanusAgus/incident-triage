# Tradeoffs and project status

## What is done

- Deterministic generator and 300 validated incidents across 12 coherent
  families.
- Idempotent `POST /ingest` with insert/skip/update counts and transactional FTS
  synchronization.
- `GET /search` with SQLite FTS5/BM25, filters, snippets, capped results, and
  totals before limiting.
- `GET /incidents/{id}` with the complete incident record.
- `POST /assist` using the same search function, one structured OpenAI Responses
  API call, explicit statuses, grounding checks, and actionable failures.
- Correlation IDs, JSON stdout logs, SQLite-backed traces/chat history, and the
  optional debug trace endpoint.
- Swagger UI and a minimal Streamlit interface.
- 110 automated tests and manual verification of all required workflows.

## What is not done

- No production or containerized deployment configuration.
- No semantic/vector search, reranker, or agentic query refinement.
- No production observability platform, dashboards, or prompt-version tracking.
- No database migration framework, load test, or CI pipeline.
- Assist requests do not accept prior conversation history.

## Assumptions

- `/assist` should select three to five incidents when that many are relevant,
  but may return fewer—or none—when the retrieved evidence does not support more.
- Search filters combine with AND. Tags require all exact,
  case-sensitive tag values; service matching is also exact and case-sensitive.
- Text terms use OR after punctuation normalization and stopword removal. Lower
  FTS5 BM25 scores represent better keyword matches.
- Ingestion is an upsert operation. Records missing from a later source file are
  retained rather than treated as deletions.
- Each assist request is independent; persisted chat history is for debugging
  and is not supplied to later model calls.
- `LLM_API_KEY` and access to the configured model are required only for
  `/assist`; ingestion, search, details, health, and documentation remain usable
  without them.

## Tradeoffs, known issues, and risks

### SQLite instead of PostgreSQL or another database

SQLite makes setup and reproduction easy and is used for this task due to its
simplicity.

For a production use case, a higher-throughput database service such as
PostgreSQL would be preferred. Direct database edits outside the ingestion path
do not synchronize the independent FTS table, and startup creates missing tables
but does not migrate existing schemas.

### FTS5/BM25 instead of hybrid search

Full-text search within SQLite is used for search. FTS5 is fast, local,
deterministic, and requires no additional service. However, because it is
keyword-based, different terminology and broad queries can reduce relevance.
Common remaining terms can produce large, weak candidate sets.

For a production use case, we should evaluate semantic or hybrid search and
possibly bounded agentic retrieval.

### Deterministic retrieval workflow

The retrieve-once-then-call-model flow is predictable, testable, inexpensive,
and easy to observe. However, it cannot reformulate a weak query or refine
retrieval based on intermediate evidence.

In a more complicated workflow, agentic RAG could allow the model to refine its
queries and run bounded tool calls as needed.

### Simple observability implementation

Observability uses JSON logs with correlation IDs and stores trace/chat records
in SQLite.

This works for a small project, but a framework such as Langfuse would be
preferred in production. Trace rows and chat history currently have no cleanup
policy, and the unauthenticated debug endpoint exposes questions and model
outputs, so it must be protected or disabled before public use.

### Stateless assist requests

Each assist request is stateless, containing one question and optional filters.
This prevents users from asking contextual follow-up questions.

It could be extended to accept prior chat history so users can ask contextual
follow-up questions.

### Swagger and a simple Streamlit interface

Swagger provides complete API exploration and Streamlit is enough for a useful
demo. Neither is as polished, accessible, or maintainable as a dedicated
product frontend.

### Limited comments and documentation

The README and module boundaries document operation and architecture, while
comments are kept targeted so required functionality fit the timebox.

Some complex areas—FTS5 SQL, grounding validation, and trace/session
interaction—would benefit from deeper developer documentation in a
longer-lived project.

## With two more hours

- Add automated end-to-end tests covering the complete application workflow.
- Add developer comments around the various implementations, particularly
  FTS5 scoring, grounding validation, and observability.
- Evaluate other search approaches and their implementation, including
  semantic and hybrid search.

## With two more days

- Add Docker and Docker Compose for reproducible API and Streamlit startup.
- Add CI for tests, formatting, linting, type checking, dataset reproducibility,
  and secret detection, including end-to-end tests for containerized startup
  and complete workflows.
- Explore bounded agentic retrieval with limited reformulation attempts and
  explicit stopping conditions.
- Integrate Langfuse for LLM traces, prompt versions, latency, token usage,
  retrieval context, failures, and evaluations.
- Expand developer documentation for maintenance and extension.
