# Phase 0 Tickets: Scaffold and Pipeline

Protocol: work tickets in order (each builds on the last). One feature branch per ticket off `dev`, verify command + full suite green, check the box, note surprises under the ticket. Escalation rules: CLAUDE.md.

Phase exit: deployed hello-world map you can log into from a phone.

---

### [x] T0.1 Backend scaffold · Complexity: S
Files: backend/pyproject.toml, backend/passage/{__init__,main,config}.py, backend/passage/api/__init__.py, backend/tests/test_health.py
Contract: specs/api-skeleton.md, specs/conventions.md
Do:
- `uv init` in backend/; add fastapi, uvicorn[standard], pydantic-settings; dev deps pytest, httpx, flake8
- Implement `create_app()`, `Settings`, `get_settings()`, and `GET /health` exactly per the contract
- Test: /health returns 200 with status+version, using TestClient and a Settings override
Accept:
- `uv run uvicorn passage.main:app` serves /health locally
- No engine/weather/db code yet; just the shell
Verify: cd backend && uv run pytest -q && uv run flake8 passage
Note: `uv init --package` defaults to a `src/` layout; used `tool.uv.build-backend.module-root = ""` in pyproject.toml to get the flat `backend/passage/` layout the conventions spec calls for. flake8 config lives in `setup.cfg` (plain flake8 doesn't read `[tool.flake8]` from pyproject.toml without a plugin). Pinned Python to 3.12.2 via `uv python pin` since the ambient default was 3.11.

### [ ] T0.2 Bearer-token auth · Complexity: S
Files: backend/passage/api/auth.py, backend/passage/api/routes.py, backend/tests/test_auth.py
Contract: specs/api-skeleton.md (Auth section)
Do:
- `require_auth` dependency on the /api router; add `GET /api/me`
- Use `secrets.compare_digest`; 401 on missing/wrong token
Accept:
- /api/me → 401 without token, 401 with wrong token, 200 `{"authenticated": true}` with correct token
- /health still unauthenticated
Verify: cd backend && uv run pytest -q

### [ ] T0.3 Frontend scaffold with map + login · Complexity: M
Files: frontend/ (Vite React-TS app), frontend/src/api/client.ts, frontend/src/components/{Login,MapView}.tsx, frontend/vite.config.ts
Contract: specs/api-skeleton.md (Frontend auth flow, Basemap), specs/conventions.md (Frontend rules)
Do:
- Scaffold Vite + React + TS (strict); add maplibre-gl
- Login screen → validates token via /api/me → stores in localStorage → shows full-screen MapLibre map (OpenFreeMap liberty style)
- client.ts: fetch wrapper adding Authorization header; on 401 clear token and surface logged-out state
- vite.config.ts: dev proxy for /api and /health → http://localhost:8000
Accept:
- With backend running: enter token, see the map; wrong token shows an error; refresh stays logged in
- `npm run build` passes tsc strict
Verify: cd frontend && npm run build
Escalate if: MapLibre/React integration fights strict TS beyond simple typing fixes (trigger 4 after two attempts)

### [ ] T0.4 Serve built frontend from FastAPI · Complexity: S
Files: backend/passage/main.py (static mount), backend/tests/test_static.py
Contract: specs/api-skeleton.md (Static serving)
Do:
- When `settings.static_dir` is set, serve it at `/` with SPA fallback to index.html for non-/api, non-/health paths
Accept:
- Test with a tmp dir containing index.html: `/` and `/some/route` return it; `/api/me` still routes to the API
- `static_dir=None` (dev) changes nothing
Verify: cd backend && uv run pytest -q

### [ ] T0.5 Dockerfile + Fly config · Complexity: M
Files: Dockerfile, .dockerignore, fly.toml
Contract: specs/conventions.md (Secrets)
Do:
- Multi-stage build: node stage builds frontend/dist; python stage (uv) installs backend and copies dist; CMD uvicorn on $PORT with PASSAGE_STATIC_DIR pointing at the copied dist
- fly.toml: single machine, volume `passage_data` mounted at /data, `PASSAGE_DATABASE_PATH=/data/passage.db`, internal port matching uvicorn, force HTTPS
Accept:
- `docker build .` succeeds; `docker run -e PASSAGE_AUTH_TOKEN=x -p 8000:8000 <img>` serves the map at localhost:8000
Verify: docker build -t passage-sim . && docker run --rm -d -e PASSAGE_AUTH_TOKEN=test -p 8000:8000 passage-sim && sleep 2 && curl -sf localhost:8000/health
Escalate if: uv-in-Docker layering gets fiddly after two attempts (trigger 4)

### [ ] T0.6 README + .env.example · Complexity: S
Files: README.md, .env.example
Contract: global documentation conventions (project objectives, architecture + justifications, structure, deployment)
Do:
- README: what the simulator is (draw from PLAN.md), architecture overview with the lazy catch-up + two-weather-planes justifications, repo structure, local dev quickstart (backend + frontend), deploy instructions (fly deploy, fly secrets set PASSAGE_AUTH_TOKEN)
- .env.example: every PASSAGE_ variable with placeholder + comment
Accept: a newcomer can go from clone to local map login using only README
Verify: manual read-through; confirm every Settings field appears in .env.example

### [ ] T0.7 First deploy · Complexity: S · USER-ASSISTED
Do (with Steven, who holds the accounts):
- Create GitHub repo (private), push main + dev; confirm CI (.github/workflows/ci.yml) is green
- `fly launch` (reuse fly.toml), create volume, `fly secrets set PASSAGE_AUTH_TOKEN=<generated>`, `fly deploy`
Accept: Steven logs in and sees the map on his phone over HTTPS
Escalate if: n/a (coordination ticket)
