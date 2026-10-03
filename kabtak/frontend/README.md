# Kabtak frontend

The Next.js App Router frontend exposes a same-origin `/api/v1` proxy. The proxy
injects the server-only internal token, while browser code never receives backend
or provider credentials.

## Setup

```bash
cp .env.example .env.local
pnpm install
pnpm generate:api
pnpm dev
```

Set `INTERNAL_API_TOKEN` to the same random value used by `../backend/.env`.
Start the FastAPI process and worker using the backend README, then open
`http://127.0.0.1:3000`.

## Checks

```bash
pnpm lint
pnpm typecheck
pnpm build
```

Regenerate `src/lib/api/generated/schema.d.ts` after changing the FastAPI
request or response models.
