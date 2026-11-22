# AI use notes

## How I used AI

I used Codex throughout the project as a coding and review partner. I used
Codex with GPT-6.1 Sol (medium) for initial planning and scaffolding, then
GPT-5.6 Sol (medium) for the remaining implementation work.

I kept the work incremental: scaffold first, then data generation, persistence, ingestion, search, assist, observability, UI, and finally an assignment audit.

AI helped with:

- scaffolding the uv/FastAPI project and module boundaries;
- generating the deterministic incident dataset and its tests;
- implementing SQLModel persistence, SQLite FTS5/BM25, and idempotent ingest;
- building the shared search path and filter/query tests;
- integrating the OpenAI Responses API with Pydantic structured output;
- writing grounding checks, failure handling, correlation logs, and trace storage;
- creating the Streamlit UI and test coverage;
- reviewing the finished project against the assignment and simplifying code and
  documentation.

I made the architectural choices and repeatedly constrained the AI to one step
at a time. I did not accept the generated implementation without review.

## My manual changes and decisions

### Direct manual edits and configuration

- Reworked `AGENTS.md` to focus the agent on this assignment and its incremental
  workflow.
- Created `.env` from the example and configured `gpt-6.1-sol`, the timeout,
  data path, SQLite URL, and port.
- Cleaned up generated configuration by moving static/default values from
  `config.py` into `constants.py` and replacing an unclear variable name.
- Added/refined the stopword policy so common question words do not dominate
  FTS matching.
- Reworked `app/prompts.py` into clearer bullet-based criteria and added explicit
  adversarial-content and prompt-injection guardrails.
- Adjusted observability so assist steps and final output are visible as JSON on
  stdout as well as through the trace endpoint.
- Manually tested the README setup and all endpoints; reviewed the
  final real-model responses, citations, drafts, and traces.

### Design corrections I directed Codex to implement

- Replaced a fixed generator count with `num_sample` parameters.
- Redesigned the repetitive dataset generation so that the generated data has more variation.
- Consolidated persistence under `app/db/` and kept SQL in `app/db/database.py` instead
  of treating queries as constants.
- Simplified the over-engineered implementation and improved variable and
  function naming.
- Added the debug trace route, SQLite correlation/chat persistence, and complete
  assist-process trace output.
- Identified repeated OpenAI client construction and requested lazy application-
  scoped reuse.

## Where AI output was weak or wrong

### 1. The first synthetic dataset was too repetitive

The initial generator technically produced 300 records but reused too few
narratives: measurement found 72 unique titles, 24 descriptions, 12 resolutions,
and only 127 unique narrative combinations. This resulted in repetition in the
generated samples.

I identified the repetition and asked for a redesign that added more variation
to the titles, descriptions, and resolutions. The generator was changed
to 36 coherent symptom/cause/resolution scenarios across 12 families, combined
with compatible workload contexts and sampled without replacement. The final
300-record dataset has 300 unique titles, descriptions, resolutions, and
narrative combinations while remaining deterministic.

### 2. The first assist implementation was over-engineered

The first version created too many custom errors and handlers for individual
OpenAI failure cases. It also placed small validation values in `constants.py`
even when they were used only once. This made a simple assist request harder to
follow because the logic was spread across unnecessary names and branches.

I adjusted the design so that the implementation was simplified to three clear
cases: missing configuration, an OpenAI request failure, or an invalid OpenAI
response. I also asked for one-off validation limits to remain beside the
Pydantic fields that use them, leaving `constants.py` for values shared across
the application.

### 3. The OpenAI client was recreated for every assist request

The initial route called `create_openai_client` whenever `/assist` was invoked.
Although functionally correct, this repeatedly constructed the SDK client and
its underlying HTTP resources instead of reusing them across requests.

I identified the repeated construction and asked for a lazy,
application-scoped client. The client is now created on the first assist request
and reused afterward, while endpoints that do not require an API key remain
usable. A lifecycle test verifies that two assist requests create one client but
still make two provider calls.

## How I validated AI-generated work

I validated the generated work in several ways:

- **Manual code review:** I read the AI-generated code to look for visible bugs,
  unclear naming, unnecessary complexity, duplicate logic, and behavior that
  did not match the assignment. This review led to several of the manual
  corrections described above.
- **Automated tests:** I ran 110 tests covering startup, schemas, data
  generation, SQLite and FTS5 behavior, ingestion, search, assist, failure
  handling, observability, and Streamlit. The tests include invalid inputs,
  filters, grounding failures, missing credentials, provider failures, and
  OpenAI client reuse.
- **Manual API and UI testing:** I used `curl`, FastAPI Swagger UI, and the
  Streamlit interface to test every endpoint. I also checked key edge cases,
  including invalid input, searches with no useful result, insufficient
  evidence, unrelated questions, and assist failures.
- **Data generation and ingestion:** I inspected the generated incidents for
  realistic variation and consistent symptom-resolution pairs. I regenerated
  the dataset to confirm deterministic output, validated all 300 records, and
  ingested it twice. The first ingest inserted 300 records and the second
  skipped all 300, confirming idempotency.
- **Search and assist output:** I manually reviewed search results to confirm
  that retrieved incidents were relevant to the query and filters. For assist
  responses, I checked that selected IDs came from retrieval, supporting
  excerpts occurred in the cited incidents, and the customer-facing draft did
  not invent the current cause, recovery status, or an ETA.
- **Debug traceability:** I retrieved the correlation trace through
  `GET /debug/trace/{correlation_id}` and confirmed that it connected the search
  input, search output, top retrieved IDs, model execution, and final selected
  incident IDs. I also confirmed that credentials were not stored in the trace.

## Prompt patterns that worked well

- **One bounded step at a time.** Asking for one endpoint or layer, its exact
  constraints, and a stop condition kept changes reviewable. It also allowed
  the AI agent to focus on the current task, reducing the risk that a long or
  complex task would cause it to overlook earlier facts, constraints, or
  instructions.
- **Define a clear code structure and design.** I did not only ask for an endpoint. 
  I also specified boundaries, such as putting ingestion logic in its own module, 
  storing SQL in `app/db/database.py`, and using one shared search function for both
  `/search` and `/assist`. This prevented the AI from placing unrelated responsibilities 
  in one file.
- **Provide examples of what correct behavior looks like.** I included sample incident 
  records to demonstrate realistic symptoms and matching resolutions. I also gave
  concrete outcomes, such as 300 inserts on the first ingest, 300 skips on the
  second, and allowing `/assist` to return fewer than three incidents when the
  evidence is limited. This gave the AI clear acceptance criteria instead of
  leaving it to interpret broad requirements.
- **Use focused follow-up prompts after reviewing the result.** Instead of
  asking for a general rewrite, I identified specific problems: a fixed sample
  count, repetitive generated records, unclear constant names, excessive error
  handling, missing trace output, and repeated OpenAI client construction. This
  produced smaller and more targeted corrections.
