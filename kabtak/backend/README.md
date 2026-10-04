# Kabtak backend

This directory contains the shared Python codebase for the FastAPI process and
the separate database-backed worker described in the system design.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are expected.

```bash
cp ../.env.example ../.env
uv sync --dev
uv run alembic upgrade head
```

The shared `../.env` template labels variables used by both services, the
frontend server only, and the backend/worker only.

Start the API on loopback:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Start the worker in a second terminal:

```bash
uv run python -m app.worker
```

The worker claims one queued run at a time, sends a heartbeat, retrieves reviewed
sources, performs structured extraction, validates every report reference against
the preserved source version, and then commits the report. Keep the API and worker
running in separate terminals. A third terminal runs the frontend from `../frontend`:

Search discovery is bounded by `MAX_SEARCH_ATTEMPTS`. A provider soft error, a
result set containing only unreviewed domains, or an allowlisted page without the
requested programme, cycle, and deadline intent advances to the next query. If
every query is exhausted, the worker uses a cycle-specific official URL from the
reviewed programme registry; the stored search record identifies this as
`registry_fallback`. The worker checks the parsed blocks again and continues past
documents that do not establish the requested deadline scope.

```bash
pnpm dev
```

The browser is available at `http://127.0.0.1:3000`. FastAPI and Next.js both
load `kabtak/.env`, so `INTERNAL_API_TOKEN` has one source of truth.

## Source and evidence guarantees

- Only hosts, path prefixes, and HTML/PDF formats listed in
  `../config/programmes/*.yaml` are fetched. Redirects are checked again.
- Each run has one shared source-request budget. Responses are streamed with a
  10 MB limit; PDFs are limited to 20 pages and parsing runs in a subprocess with
  a 10-second timeout by default.
- Original bytes and parser-versioned evidence blocks are written once under
  `DATA_DIR/sources`. Both the document and every evidence block have SHA-256
  hashes.
- Extractions are cached only for the same document version, model, prompt, and
  schema. Block IDs and dates are validated before a report is committed.
- Source, PDF, parser, and extraction failures are persisted as explicit safe
  states; they cannot become a confident answer.
- `GET /v1/runs/{run_id}/evidence/{version_id}/{block_id}` verifies the stored
  hashes before returning a passage and its provenance.

When an API schema changes, refresh the generated frontend contract:

```bash
uv run python scripts/export_openapi.py
cd ../frontend && pnpm generate:api
```

## Checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The live path requires `SERPAPI_API_KEY` and a Groq `LLM_API_KEY`. Keep
secrets in `kabtak/.env`; only `kabtak/.env.example` is committed.
