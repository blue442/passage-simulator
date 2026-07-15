# CONTRACT: Deployment (Vercel + Supabase)

Frozen by the Pre-0.5 spec session (2026-07-14). Supersedes the Fly.io deployment decided at Pre-0 (rationale recorded in tickets/phase-0.md under T0.7). Implementation sessions follow this; changes require a spec session.

## Shape

Two Vercel projects deployed from one GitHub repo via Git integration (push to `main` → production; `dev` and feature branches → preview deployments):

| Vercel project | Root directory | Preset | Serves |
|---|---|---|---|
| `passage-api` | `backend/` | FastAPI (Python runtime) | `/health`, `/api/*` |
| `passage-frontend` | `frontend/` | Vite | the SPA, plus proxy rewrites |

The browser only ever talks to the frontend domain. `frontend/vercel.json` rewrites `/api/:path*` and `/health` to the backend project's production URL, so the origin is single and the bearer-token flow needs no CORS handling. The backend's own domain is an implementation detail (it still serves requests directly; nothing must break if hit directly).

- Backend Python runtime installs from `backend/pyproject.toml` + `uv.lock` (Vercel's installer uses uv; commit the lockfile, it is authoritative). Python version comes from `backend/.python-version` (3.12).
- Entrypoint: `[tool.vercel] entrypoint = "passage.main:app"` in `backend/pyproject.toml` — Vercel requires `module:object` format (dotted module path, not a file path), corrected at T0V.7 after a real deploy rejected the file-path form.
- `backend/vercel.json` sets `functions` `maxDuration` = 60 and the keep-alive cron (below).
- `backend/.vercelignore` excludes `tests/`.

## Database

Supabase Postgres, accessed as **plain Postgres only**: `psycopg` + SQL. No supabase-py, no PostgREST, no Supabase Auth/Realtime/Storage. This keeps the app portable and the code boring.

- Runtime connections use the **pooled** connection string (Supavisor, transaction mode, port 6543). Serverless functions must not hold direct connections.
- Transaction-mode pooling breaks server-side prepared statements: the shared connection helper must set `prepare_threshold=None`. This is a correctness requirement, not an optimization; symptoms of getting it wrong are intermittent `prepared statement "..." does not exist` errors.
- Config: `PASSAGE_DATABASE_URL` (full DSN). `Settings.database_url: str`, required. The old `database_path` is gone.
- Migrations are plain SQL files in `supabase/migrations/`, managed with the Supabase CLI (`supabase migration new`, applied locally by `supabase db reset`, to production by `supabase db push`). Application code never runs migrations.
- Local development and tests run against the Supabase CLI local stack (`supabase start`; Postgres at `127.0.0.1:54322`). CI uses a plain `postgres` service container and applies `supabase/migrations/*.sql` with `psql` — migrations must therefore stay valid vanilla Postgres SQL.
- Preview deployments share the production database (single-user app; revisit if passage history becomes precious).

## Keep-alive

Supabase pauses free-tier projects after ~7 days without database activity, and eventually deletes long-paused projects. Mitigation is designed in, not left to memory:

- `GET /api/cron/keepalive`: runs `SELECT 1`, returns `{"database": "ok"}`. Authenticated by `Authorization: Bearer <CRON_SECRET>` (Vercel cron convention), **not** by the user token; 401 otherwise. Lives under `/api` but is excluded from the router-level `require_auth` (it has its own dependency).
- `backend/vercel.json` schedules it daily. Hobby-plan cron timing is imprecise (within an hour window); daily is comfortably inside Supabase's 7-day threshold.
- `/health` stays DB-free on purpose: it must answer fast and must not wake the database.

## Environment variables

All set in the Vercel dashboard (backend project), Production + Preview scopes:

| Var | Meaning |
|---|---|
| `PASSAGE_AUTH_TOKEN` | single-user bearer token (unchanged) |
| `PASSAGE_DATABASE_URL` | Supabase **pooled** DSN |
| `CRON_SECRET` | shared secret for Vercel cron → keepalive endpoint |

`PASSAGE_STATIC_DIR` no longer exists: Vercel's CDN serves the frontend, and FastAPI serves no static files in any environment.

## Constraint recorded for the Pre-1 gate: chunked catch-up

Vercel functions are time-boxed (60s configured; Hobby ceiling is low regardless). The lazy catch-up design must therefore be **chunkable from its first version**: the check-in endpoint contract designed at Pre-1 must let the engine simulate a bounded slice of elapsed time per request (budget in config, e.g. `PASSAGE_MAX_CATCHUP_HOURS_PER_REQUEST`), persist progress, and report `caught_up: bool` so the client loops until current. Determinism is unaffected (cached weather + per-passage seed, chunk boundaries must not change outcomes — the replay test should cover a chunked vs unchunked run). Do not design a single-shot check-in API.

## Known limits accepted with this choice

- Hobby plan is for personal, non-commercial use (this qualifies).
- Function time limits make long syntheses (e.g. Phase 4 GRIB decode with cfgrib/eccodes) a risk: heavy native deps may also exceed function size limits. Flagged for the Pre-4 gate; likely resolution is doing GRIB subsetting/decoding in a different way (smaller lib, or precomputing) — not this contract's problem yet.
- Supabase free tier is 500MB of database; the Phase-1 weather cache lives in Postgres and must get a pruning story at Pre-1 (old model runs are never needed once a passage ends).
