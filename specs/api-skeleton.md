# CONTRACT: API Skeleton (Phase 0)

Frozen by the Pre-0 spec session (2026-07-14). Defines the app shell that Phase 1+ builds on.

## App factory

`passage/main.py` exposes `create_app() -> FastAPI`. Nothing at module import time does I/O. Uvicorn entrypoint: `passage.main:app` where `app = create_app()`.

## Settings

`passage/config.py` defines `Settings(BaseSettings)` with `env_prefix = "PASSAGE_"`:

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `auth_token: str` | `PASSAGE_AUTH_TOKEN` | (required) | Single-user bearer token |
| `database_path: Path` | `PASSAGE_DATABASE_PATH` | `./data/passage.db` | SQLite location (Fly volume mounts here in prod) |
| `static_dir: Path \| None` | `PASSAGE_STATIC_DIR` | `None` | Built frontend to serve; None in dev (Vite proxies instead) |

Access via a `get_settings()` dependency (cached), never a module-level singleton, so tests can override.

## Auth

- Scheme: `Authorization: Bearer <token>`, compared against `settings.auth_token` with `secrets.compare_digest`.
- FastAPI dependency `require_auth` applied to the `/api` router as a whole, not per-endpoint.
- Unauthenticated/wrong token → 401 with FastAPI-default body `{"detail": "..."}`.
- `/health` is outside `/api` and unauthenticated.

## Endpoints (Phase 0 scope)

| Method+Path | Auth | Response |
|---|---|---|
| `GET /health` | no | `{"status": "ok", "version": "<package version>"}` |
| `GET /api/me` | yes | `{"authenticated": true}` (exists so the frontend can validate a token) |

Phase 1 adds `/api/passages...`; those contracts come at the Pre-1 gate.

## Static serving

When `settings.static_dir` is set, mount the built frontend at `/` (SPA fallback to `index.html` for unknown non-`/api` paths). In development the Vite dev server proxies `/api` and `/health` to `localhost:8000`.

## Frontend auth flow

- Token entered on a minimal login screen, validated via `GET /api/me`, kept in `localStorage` under `passage.token`.
- Any 401 from the API clears the token and returns to login.

## Basemap

MapLibre GL with the OpenFreeMap `liberty` style (`https://tiles.openfreemap.org/styles/liberty`) — free, no API key. Revisit for a more nautical look in Phase 7; the style URL lives in one constant.
