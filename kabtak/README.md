# Kabtak

Kabtak is a Next.js frontend with a Python/FastAPI backend and a separate
database-backed worker. The backend structure follows the architecture in
[`../docs/system-design.md`](../docs/system-design.md).

## Applications

- `frontend/` — Next.js App Router application
- `backend/` — FastAPI application and worker
- `config/programmes/` — reviewed scholarship and source policies
- `examples/` — offline historical replay fixtures
- `evaluation/` — evaluation manifests, runner, and results
- `data/` — ignored local SQLite databases, snapshots, caches, and logs

See the README in each application directory for its setup commands.
