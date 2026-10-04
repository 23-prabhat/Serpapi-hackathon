# Kabtak application

Kabtak is a Next.js frontend with a Python/FastAPI backend and a separate
database-backed worker. Start with the [repository README](../README.md) for the
product, architecture, scope, evaluation, SerpApi integration, and limitations.
The backend structure follows the architecture in
[`../docs/system-design.md`](../docs/system-design.md).

## Applications

- `frontend/` — Next.js App Router application
- `backend/` — FastAPI application and worker
- `config/programmes/` — reviewed scholarship and source policies
- `examples/` — offline historical replay fixtures
- `evaluation/` — evaluation manifests, runner, and results
- `data/` — ignored local SQLite databases, snapshots, caches, and logs
- `.env.example` — one annotated environment template shared by every process

Copy `.env.example` to `.env`, then see the repository README and `run.md` for
setup, startup, verification, and the credential-free example.
