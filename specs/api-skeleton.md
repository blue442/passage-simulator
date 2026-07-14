# CONTRACT: API Skeleton (Phase 0)

Frozen by the Pre-0 spec session (2026-07-14); amended by the Pre-0.5 spec session (same date) for the Vercel + Supabase deployment — see specs/deployment.md. Defines the app shell that Phase 1+ builds on.

## App factory

`passage/main.py` exposes `create_app() -> FastAPI`. Nothing at module import time does I/O (no settings resolution, no DB connection). Module-level `app = create_app()` is the entrypoint for both local uvicorn (`passage.main:app`) and Vercel's Python runtime.

## Settings

`passage/config.py` defines `Settings(BaseSettings)` with `env_prefix = "PASSAGE_"`:

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `auth_token: str` | `PASSAGE_AUTH_TOKEN` | (required) | Single-user bearer token |
| `database_url: str` | `PASSAGE_DATABASE_URL` | (required) | Postgres DSN. Production: Supabase pooled (Supavisor) URL. Local: Supabase CLI stack. |
| `cron_secret: str` | `CRON_SECRET` | (required) | Secret for Vercel cron → keepalive. Note: no `PASSAGE_` prefix — Vercel's cron convention names it `CRON_SECRET`, so it is declared with an explicit `alias`. |

Access via a `get_settings()` dependency (cached), never a module-level singleton, so tests can override.

## Database access

`passage/db/` owns all Postgres access: a connection helper around `psycopg` that (a) reads `settings.database_url`, (b) sets `prepare_threshold=None` (required by Supavisor transaction-mode pooling), (c) opens per-request, short-lived connections. No ORM. Schema changes only via `supabase/migrations/*.sql`. Engine code (`passage/engine/`, Phase 1+) never imports `passage.db`.

## Auth

- Scheme: `Authorization: Bearer <token>`, compared against `settings.auth_token` with `secrets.compare_digest`.
- FastAPI dependency `require_auth` applied to the `/api` router as a whole, not per-endpoint.
- Unauthenticated/wrong token → 401 with FastAPI-default body `{"detail": "..."}`.
- `/health` is outside `/api` and unauthenticated.
- Exception: `/api/cron/keepalive` authenticates against `CRON_SECRET` instead (own router, not under the `require_auth` router).

## Endpoints (Phase 0 scope)

| Method+Path | Auth | Response |
|---|---|---|
| `GET /health` | no | `{"status": "ok", "version": "<package version>"}` — must not touch the DB |
| `GET /api/me` | user token | `{"authenticated": true}` (exists so the frontend can validate a token) |
| `GET /api/cron/keepalive` | `CRON_SECRET` | `{"database": "ok"}` after a successful `SELECT 1`; 401 on bad/missing secret |

Phase 1 adds `/api/passages...`; those contracts come at the Pre-1 gate (and must honor the chunked catch-up constraint in specs/deployment.md).

## Static serving

None. FastAPI serves no static files in any environment: Vercel's CDN serves the built frontend, and in development the Vite dev server proxies `/api` and `/health` to `localhost:8000`.

## Frontend auth flow

- Token entered on a minimal login screen, validated via `GET /api/me`, kept in `localStorage` under `passage.token`.
- Any 401 from the API clears the token and returns to login.

## Basemap

MapLibre GL with the OpenFreeMap `liberty` style (`https://tiles.openfreemap.org/styles/liberty`) — free, no API key. Revisit for a more nautical look in Phase 7; the style URL lives in one constant.
