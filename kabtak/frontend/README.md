# Kabtak frontend

The Next.js App Router frontend exposes a same-origin `/api/v1` proxy. The proxy
injects the server-only internal token, while browser code never receives backend
or provider credentials.

## Setup

```bash
cp ../.env.example ../.env
pnpm install
pnpm generate:api
pnpm dev
```

The shared template separates common, frontend-only, and backend-only values.
Next.js loads `../.env` on the server; secrets are not prefixed with
`NEXT_PUBLIC_` and are therefore not exposed to browser code.
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
