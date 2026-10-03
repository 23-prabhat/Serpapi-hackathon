# Kabtak backend

This directory contains the shared Python codebase for the FastAPI process and
the separate database-backed worker described in the system design.

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/) are expected.

```bash
cp .env.example .env
uv sync --dev
uv run alembic upgrade head
```

Start the API on loopback:

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Start the worker in a second terminal:

```bash
uv run python -m app.worker
```

The worker claims one queued run at a time, sends a heartbeat, retrieves reviewed
sources, performs structured extraction, and commits the report. Keep the API and
worker running in separate terminals. A third terminal runs the frontend from
`../frontend`:

Search discovery is bounded by `MAX_SEARCH_ATTEMPTS`. A provider soft error or a
result set containing only unreviewed domains advances to the next query. If every
query is exhausted, the worker may use a cycle-specific official URL from the
reviewed programme registry; the stored search record identifies this as
`registry_fallback`.

```bash
pnpm dev
```

The browser is available at `http://127.0.0.1:3000`. `INTERNAL_API_TOKEN` must
match in `backend/.env` and `frontend/.env.local`.

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

The live Phase 1 path requires `SERPAPI_API_KEY` and a Groq `LLM_API_KEY`. Keep
secrets in `.env`; only `.env.example` is committed.
