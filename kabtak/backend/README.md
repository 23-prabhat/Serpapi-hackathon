# Kabtak backend

This directory contains the shared Python codebase for the FastAPI process and
the separate worker process. It intentionally starts with a thin health path;
the remaining modules define the boundaries described in the system design.

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

The worker currently exposes its entry point and configuration boundary; queue
claiming and processing are the next persistence implementation step.

## Checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Live credentials are optional for the scaffold. Keep secrets in `.env`; only
`.env.example` is committed.
