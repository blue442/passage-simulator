# CONTRACT: Repo Conventions

Frozen by the Pre-0 spec session (2026-07-14); amended by the Pre-0.5 spec session (same date) for the Vercel + Supabase deployment. Implementation sessions follow this; changes require a spec session.

## Layout

```
backend/
  pyproject.toml        # uv-managed; run all backend commands from backend/
  passage/              # the Python package
    main.py             # FastAPI app factory: create_app()
    config.py           # Settings via pydantic-settings
    api/                # routers only; no business logic
    engine/             # PURE simulation core; no I/O, no network, no clock reads
    weather/            # Open-Meteo client + cache
    gribs/              # NOMADS download + decode (Phase 4)
    geo/                # coordinate math, land mask
    db/                 # Postgres access (psycopg); schema lives in supabase/migrations
  tests/                # mirrors package layout: tests/engine/, tests/weather/, ...
  vercel.json           # backend Vercel project config (maxDuration, cron)
frontend/
  package.json          # Vite + React + TypeScript
  src/
  vercel.json           # frontend Vercel project config (proxy rewrites to the API)
supabase/
  config.toml           # Supabase CLI local-stack config
  migrations/           # plain-SQL migrations; the only place schema changes happen
specs/                  # frozen contracts; do not edit in implementation sessions
tickets/                # phase-N.md work orders
reference/              # Steven's sailing reference material; not part of the app
```

## Backend rules

- Python 3.12+. uv for everything: `uv run pytest`, `uv run flake8`, `uv add <dep>`.
- Type hints on all function signatures. Descriptive names, no abbreviations.
- flake8 with E501 ignored (config in backend/pyproject.toml or setup.cfg).
- `engine/` purity: functions in `passage/engine/` never import httpx/requests/psycopg/passage.db/datetime-now. Time, weather, and randomness enter as parameters. A test may enforce this by import inspection.
- Database: plain SQL via `psycopg` through `passage/db/` only — no ORM, no supabase-py. Schema changes only as new files in `supabase/migrations/`, which must remain valid vanilla Postgres (CI applies them with `psql`). See specs/deployment.md.
- Pydantic models for all API request/response bodies and engine state objects.
- Every ticket lands with tests. Full suite (`uv run pytest`) must pass before a ticket is marked done.

## Frontend rules

- Vite + React 18 + TypeScript (strict). MapLibre GL for the map. Plain CSS (one stylesheet per component area); no CSS framework for now.
- No state library; React hooks + context. Keep components small and typed.
- API access only through `src/api/client.ts` (single fetch wrapper handling auth + errors).
- `npm run build` (tsc + vite build) must pass before a ticket is marked done.

## Git

- Branches: `main` (stable) ← `dev` (integration) ← `feature/*` or `fix/*`.
- One ticket = one commit minimum, on a feature branch off dev, message `T0.3: <what changed>`.
- Never commit `.env`. `.env.example` documents every variable.

## Secrets and config

- All runtime config via environment variables prefixed `PASSAGE_` (one deliberate exception: `CRON_SECRET`, named by Vercel's cron convention), loaded from `.env` at repo root in development, from Vercel project env vars in production and previews.
