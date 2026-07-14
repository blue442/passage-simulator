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
frontend/  (Vite + TypeScript + MapLibre GL)
  Tracker map, login screen, check-in UI (grows with each phase)

backend/   (FastAPI, Python, uv)
  passage/
    main.py     FastAPI app factory: create_app()
    config.py   Settings (env-driven, PASSAGE_ prefix)
    api/        routers only; no business logic
    engine/     PURE simulation core — no I/O, no network, no clock reads (Phase 1+)
    weather/    Open-Meteo client + cache (Phase 1+)
    gribs/      NOMADS download + decode (Phase 4+)
    geo/        coordinate math, land mask (Phase 1+)
    db/         SQLite access, schema migrations (Phase 1+)
  tests/        mirrors package layout
```

### Key design decisions

**Lazy catch-up simulation.** Nothing runs between check-ins. When you open the app, the engine
simulates forward from the last simulated timestamp to *now*, using actual recorded weather for
the elapsed period. This means no 24/7 background worker (the server can sleep, which is why
`fly.toml` lets machines auto-stop/auto-start), and the weather your boat experienced is what
really happened at that position and time. Determinism follows from this: weather responses are
cached and the event RNG is seeded per passage, so a catch-up can always be replayed identically.

**Two weather planes, on purpose.** The engine's ground truth (Open-Meteo) and the data you plan
with (real GFS/WaveWatch III GRIBs, same as a real skipper would pull) are different views of
similar models. Your plan is only as good as your forecast reading — that gap is the point.

**The engine is pure.** `backend/passage/engine/` takes `(state, weather samples, orders, seed)`
and returns `(new state, log events)`. No I/O lives inside it, which makes it fast to unit-test
against synthetic weather and makes replay/debrief trivial to implement later.

## Repo structure

```
backend/     FastAPI app (uv-managed)
frontend/    Vite + React + TypeScript + MapLibre GL
specs/       frozen contracts for the current phase
tickets/     phase-N.md work orders
reference/   Steven's sailing reference material, not part of the app
```

## Local development

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node 22+.

1. Copy `.env.example` to `.env` at the repo root and set `PASSAGE_AUTH_TOKEN` to something you'll
   remember (this is your login token, not a real secret yet).

2. Backend:
   ```
   cd backend
   uv sync --all-extras --dev
   uv run uvicorn passage.main:app --reload
   ```
   Serves the API at `http://localhost:8000`. `GET /health` is unauthenticated; everything under
   `/api` requires `Authorization: Bearer <PASSAGE_AUTH_TOKEN>`.

3. Frontend, in a second terminal:
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

The app ships as a single Docker image: a Node stage builds the frontend, a Python (uv) stage
installs the backend and serves the built frontend as static files with an SPA fallback.

```
fly launch      # first time only; reuses fly.toml
fly volumes create passage_data --size 1   # first time only
fly secrets set PASSAGE_AUTH_TOKEN=$(openssl rand -hex 32)
fly deploy
```

`fly.toml` mounts a volume at `/data` for the SQLite database and forces HTTPS. Machines are
allowed to auto-stop when idle and auto-start on the next request — safe because of the lazy
catch-up design above; there's nothing that needs to run while no one is checking in.
