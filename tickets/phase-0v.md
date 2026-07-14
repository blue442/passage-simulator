# Phase 0.5 Tickets: Vercel + Supabase Migration

Produced by the Pre-0.5 spec session (2026-07-14, Fable). Steven chose Vercel + Supabase over Fly.io after the hosting-cost discussion recorded in tickets/phase-0.md (T0.7 Blocked section). Contracts: specs/deployment.md (new), specs/api-skeleton.md and specs/conventions.md (amended), PLAN.md (hosting rows updated).

Protocol: same as phase 0 — work tickets in order, one feature branch per ticket off `dev`, verify command + full suite green, check the box, note surprises. Escalation rules: CLAUDE.md.

Phase exit (replaces T0.7): deployed hello-world map on Vercel you can log into from a phone, with the keepalive cron proving the Supabase connection.

Prereq for T0V.2 onward: local Supabase stack (`supabase start` from repo root; requires Docker running). Local Postgres DSN: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`.

---

### [x] T0V.1 Remove Fly artifacts and static serving · Complexity: S
Files: Dockerfile (delete), .dockerignore (delete), fly.toml (delete), backend/passage/main.py, backend/passage/config.py, backend/tests/test_static.py (delete), .env.example
Contract: specs/deployment.md (Shape), specs/api-skeleton.md (Static serving: none)
Do:
- Delete Dockerfile, .dockerignore, fly.toml
- Remove the `serve_frontend` catch-all route from main.py and `static_dir` from Settings; delete tests/test_static.py
- Remove the PASSAGE_STATIC_DIR block from .env.example
Accept:
- `grep -ri "static_dir\|fly.toml\|Dockerfile" backend/ .env.example` finds nothing (README still mentions them; T0V.6 rewrites it)
- /health and /api/me behavior unchanged
Verify: cd backend && uv run pytest -q && uv run flake8 passage
Note: left `database_path`/`Path` on Settings untouched here since T0V.2 owns that swap; only `static_dir` came out. No surprises.

### [x] T0V.2 Postgres settings + db module + first migration · Complexity: M
Files: backend/passage/config.py, backend/passage/db/__init__.py, backend/pyproject.toml (add psycopg), supabase/config.toml, supabase/migrations/<ts>_init_app_meta.sql, backend/tests/test_db.py, .env.example
Contract: specs/deployment.md (Database), specs/api-skeleton.md (Settings, Database access)
Do:
- Settings: replace `database_path: Path` with `database_url: str` (required); add `cron_secret: str` with `Field(alias="CRON_SECRET")` (it has no PASSAGE_ prefix) and `populate_by_name=True` in `model_config` so tests can construct `Settings(cron_secret=...)`
- Update existing tests that construct `Settings(auth_token=...)` to also pass `database_url` and `cron_secret`
- `uv add "psycopg[binary]"`
- `passage/db/__init__.py`: a `get_connection(settings)` contextmanager wrapping `psycopg.connect(settings.database_url)`; set `conn.prepare_threshold = None` immediately after connect (required for Supavisor transaction pooling — see specs/deployment.md, do not skip)
- `supabase init` at repo root (creates supabase/config.toml); `supabase migration new init_app_meta` with:
  `create table app_meta (key text primary key, value text not null);`
  `insert into app_meta (key, value) values ('schema', 'phase-0.5');`
- tests/test_db.py: reads DSN from `PASSAGE_DATABASE_URL` env, defaulting to the local Supabase DSN above; asserts `select value from app_meta where key = 'schema'` returns `phase-0.5`
- Update .env.example: replace database_path block with PASSAGE_DATABASE_URL (document pooled-URL requirement for prod) and add CRON_SECRET
Accept:
- `supabase start && supabase db reset` applies the migration cleanly
- Test suite passes against the local stack
Verify: supabase db reset && cd backend && uv run pytest -q && uv run flake8 passage
Escalate if: psycopg/Supavisor connection behavior is surprising (trigger 3/4), or Settings alias handling fights pydantic-settings after two attempts
Note: `Field(alias="CRON_SECRET")` + `populate_by_name=True` on `model_config` worked on the first try — pydantic-settings respects an explicit field alias over `env_prefix` for that one field, and `populate_by_name` lets tests construct `Settings(cron_secret=...)` by name instead of by alias. Local Supabase CLI binary needed manual reinstall (unrelated packaging snag from the earlier `brew` fallback, not a contract issue) but once running, `supabase init` / `migration new` / `start` / `db reset` all behaved exactly as specced — local DSN matched `postgresql://postgres:postgres@127.0.0.1:54322/postgres` exactly.

### [ ] T0V.3 Keep-alive cron endpoint · Complexity: S
Files: backend/passage/api/cron.py, backend/passage/main.py, backend/tests/test_cron.py
Contract: specs/api-skeleton.md (Endpoints, Auth exception), specs/deployment.md (Keep-alive)
Do:
- New router (prefix `/api/cron`) NOT mounted under the require_auth router; own dependency comparing the bearer token to `settings.cron_secret` via `secrets.compare_digest`
- `GET /api/cron/keepalive`: `select 1` through `passage.db.get_connection`, return `{"database": "ok"}`
Accept:
- 401 without/with wrong secret; 200 + `{"database": "ok"}` with correct secret (against local stack)
- User token does NOT authorize the cron endpoint, and CRON_SECRET does not authorize /api/me
Verify: cd backend && uv run pytest -q && uv run flake8 passage

### [ ] T0V.4 Vercel project config · Complexity: S
Files: backend/pyproject.toml, backend/vercel.json, backend/.vercelignore, frontend/vercel.json
Contract: specs/deployment.md (Shape, Keep-alive)
Do:
- backend/pyproject.toml: add `[tool.vercel]` with `entrypoint = "passage/main.py"`
- backend/vercel.json: `{"functions": {"passage/main.py": {"maxDuration": 60}}, "crons": [{"path": "/api/cron/keepalive", "schedule": "0 12 * * *"}]}`
- backend/.vercelignore: `tests/`
- frontend/vercel.json: rewrites for `/api/:path*` and `/health` to `https://passage-api.vercel.app` (placeholder domain — T0V.7 confirms the real one and updates this file)
Accept:
- All JSON valid; local behavior unchanged (these files are inert outside Vercel)
- Note: real validation happens at T0V.7's first deploy. If the deploy later rejects the `functions` key pattern for the FastAPI preset, that's a config-shape question — consult Vercel docs once, then escalate (trigger 4), don't guess repeatedly.
Verify: cd backend && uv run pytest -q && python -c "import json; json.load(open('vercel.json')); json.load(open('../frontend/vercel.json'))"

### [ ] T0V.5 CI: Postgres service for backend tests · Complexity: S
Files: .github/workflows/ci.yml
Contract: specs/deployment.md (Database — CI applies migrations with psql)
Do:
- backend job: add a `postgres:17` service (POSTGRES_PASSWORD=postgres, port 5432, health-cmd pg_isready); before pytest, apply migrations: `for f in ../supabase/migrations/*.sql; do psql "$PASSAGE_DATABASE_URL" -f "$f"; done` (note working-directory is backend/)
- Job env: `PASSAGE_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres`, `PASSAGE_AUTH_TOKEN=ci-test`, `CRON_SECRET=ci-test`
Accept:
- Workflow YAML is valid; the psql loop applies migrations in filename (timestamp) order
- Frontend job unchanged
Verify: cd backend && uv run pytest -q  (full CI validation lands with T0V.7's repo push)

### [ ] T0V.6 README + .env.example final pass · Complexity: S
Files: README.md, .env.example
Contract: global documentation conventions; specs/deployment.md
Do:
- Rewrite README deployment + architecture sections: Vercel two-project shape with the frontend proxy, Supabase Postgres (pooled URL, keep-alive cron and why), local dev now includes `supabase start`, deploy-by-git-push (main → production, branches → previews)
- Keep the lazy catch-up + two-weather-planes explanations; add the chunked catch-up constraint note
- Confirm every Settings field appears in .env.example with comments (auth_token, database_url, cron_secret)
Accept: a newcomer goes clone → `supabase start` → backend → frontend → map login using only README
Verify: manual read-through; grep confirms no Fly/Docker references remain anywhere but git history and ticket notes

### [ ] T0V.7 First deploy · Complexity: M · USER-ASSISTED
Do (with Steven, who holds all accounts):
- GitHub: create private repo under Steven's PERSONAL account (Hobby plan cannot link org repos), push main + dev, confirm CI green
- Supabase: create project (region near ord), `supabase link`, `supabase db push`; copy the POOLED connection string (Supavisor, port 6543 — not the direct 5432 one)
- Vercel: create project `passage-api` (root dir backend/, FastAPI preset) and `passage-frontend` (root dir frontend/, Vite preset); set PASSAGE_AUTH_TOKEN (generate: `openssl rand -hex 32`), PASSAGE_DATABASE_URL (pooled), CRON_SECRET (generate) on the backend project, Production + Preview scopes
- Update frontend/vercel.json rewrite destinations to the backend project's real production domain; commit, push, redeploy
- Verify: `curl https://<backend-domain>/health` works; keepalive returns 200 with the secret and 401 without; cron shows a successful run in Vercel logs within a day
Accept: Steven logs in and sees the map on his phone over HTTPS at the frontend domain
Escalate if: FastAPI preset/entrypoint or uv install behaves differently than specs/deployment.md assumes — that's a contract update, bring it back to a spec session (trigger 2)
