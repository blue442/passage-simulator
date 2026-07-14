# Passage Simulator

A web-based sail passage simulator for honing ocean passage-planning skills. Think ocean race
tracker meets Windy, with an Oregon Trail heart: a simulated boat sails real-time through real
weather, you check in once or twice a day, read the captain's log of what happened since you
left, study the forecast, and issue new orders.

The full vision and phased roadmap live in [PLAN.md](PLAN.md); the AI-assisted build workflow is
in [EXECUTION.md](EXECUTION.md). This README covers what's needed to run and deploy what exists
today.

## Architecture

```
frontend/  (Vite + TypeScript + MapLibre GL) — deployed as its own Vercel project
  Tracker map, login screen, check-in UI (grows with each phase)

backend/   (FastAPI, Python, uv) — deployed as its own Vercel project (Python function)
  passage/
    main.py     FastAPI app factory: create_app()
    config.py   Settings (env-driven, PASSAGE_ prefix)
    api/        routers only; no business logic
    engine/     PURE simulation core — no I/O, no network, no clock reads (Phase 1+)
    weather/    Open-Meteo client + cache (Phase 1+)
    gribs/      NOMADS download + decode (Phase 4+)
    geo/        coordinate math, land mask (Phase 1+)
    db/         Postgres access (psycopg), no ORM
  tests/        mirrors package layout

supabase/  migrations/ — plain-SQL schema, applied via the Supabase CLI
```

### Key design decisions

**Lazy catch-up simulation.** Nothing runs between check-ins. When you open the app, the engine
simulates forward from the last simulated timestamp to *now*, using actual recorded weather for
the elapsed period. This means no 24/7 background worker — which is also exactly the shape
serverless functions want, which is why the app deploys to Vercel rather than a boxes-and-volumes
host — and the weather your boat experienced is what really happened at that position and time.
Determinism follows from this: weather responses are cached and the event RNG is seeded per
passage, so a catch-up can always be replayed identically. Because a serverless function's
execution time is bounded, catch-up is designed to run in bounded chunks per request rather than
simulating an arbitrarily long gap in one call (see specs/deployment.md) — the client just calls
check-in repeatedly until the response reports it's caught up.

**Two weather planes, on purpose.** The engine's ground truth (Open-Meteo) and the data you plan
with (real GFS/WaveWatch III GRIBs, same as a real skipper would pull) are different views of
similar models. Your plan is only as good as your forecast reading — that gap is the point.

**The engine is pure.** `backend/passage/engine/` takes `(state, weather samples, orders, seed)`
and returns `(new state, log events)`. No I/O lives inside it, which makes it fast to unit-test
against synthetic weather and makes replay/debrief trivial to implement later.

## Repo structure

```
backend/     FastAPI app (uv-managed), its own Vercel project
frontend/    Vite + React + TypeScript + MapLibre GL, its own Vercel project
supabase/    Supabase CLI config and migrations (plain SQL, no ORM)
specs/       frozen contracts for the current phase
tickets/     phase-N.md work orders
reference/   Steven's sailing reference material, not part of the app
```

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 22+, Docker (for the local Supabase
stack), and the [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started).

1. Copy `.env.example` to `.env` at the repo root and set `PASSAGE_AUTH_TOKEN` and `CRON_SECRET` to
   anything memorable (these are dev-only values, not real secrets yet).

2. Start the local database (from the repo root):
   ```
   supabase start
   ```
   This runs Postgres in Docker at `postgresql://postgres:postgres@127.0.0.1:54322/postgres` —
   already the default in `.env.example` — and applies everything in `supabase/migrations/`.
   Re-run `supabase db reset` after pulling new migrations.

3. Backend:
   ```
   cd backend
   uv sync --all-extras --dev
   uv run uvicorn passage.main:app --reload
   ```
   Serves the API at `http://localhost:8000`. `GET /health` is unauthenticated and never touches
   the database; everything under `/api` requires `Authorization: Bearer <PASSAGE_AUTH_TOKEN>`,
   except `/api/cron/keepalive`, which requires `Authorization: Bearer <CRON_SECRET>` instead.

4. Frontend, in a second terminal:
   ```
   cd frontend
   npm install
   npm run dev
   ```
   Serves the app at `http://localhost:5173`, proxying `/api` and `/health` to the backend above.
   Open it, enter your token, and you should see a full-screen map.

Run the backend test suite and linter before considering any change done:
```
cd backend && uv run pytest -q && uv run flake8 passage
```

## Deploying

Two Vercel projects deploy from this one repo via Vercel's Git integration: `passage-api` (root
directory `backend/`, FastAPI/Python runtime) and `passage-frontend` (root directory `frontend/`,
Vite). Pushing to `main` deploys to production; every other branch gets its own preview URL. The
frontend's `vercel.json` proxies `/api/*` and `/health` to the backend project, so the browser only
ever talks to one origin and the bearer-token flow needs no CORS handling.

The database is Supabase Postgres. Schema changes are plain SQL files in `supabase/migrations/`,
pushed with the Supabase CLI (`supabase db push`) — the application itself never runs migrations.
Because Supabase pauses free-tier projects after about a week of inactivity, a daily Vercel cron
job hits `GET /api/cron/keepalive` (see specs/deployment.md) to keep the database awake between
check-ins; `/health` deliberately stays database-free so it can answer fast and never wakes it.

First-time setup (see `tickets/phase-0v.md`, T0V.7, for the full walkthrough):
```
# Supabase: create a project, then
supabase link
supabase db push

# Vercel: create both projects, then set on the backend project
# (Production + Preview scopes): PASSAGE_AUTH_TOKEN, PASSAGE_DATABASE_URL
# (the Supabase project's POOLED/Supavisor connection string, not the direct
# one — serverless functions must not hold direct connections), CRON_SECRET
```
