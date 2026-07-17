# Phase 1 Tickets: Core Engine MVP

Produced by the Pre-1 spec session (2026-07-15, Opus). Contracts frozen this gate:
`specs/engine-state.md`, `specs/orders.md`, `specs/weather-cache.md`, `specs/golden-fixtures.md`,
and the migration `supabase/migrations/20260715120000_phase1_schema.sql` (already applied locally;
push to prod happens in T1.11 verification / at deploy). Read those before starting — they are the
authority; this file only sequences the work.

Protocol (same as phase 0): work tickets in order, one feature branch per ticket off `dev`, verify
command + full suite green, check the box, add a one-line note of anything surprising. Escalation
rules: CLAUDE.md / EXECUTION.md. The engine purity rule and the sacred determinism/replay test
(GF-6) are load-bearing — a failure there is an automatic escalation, never a loosened assertion.

**Phase exit:** create a passage via API, come back (or start it in the past) and check in, see a
believable track and hourly conditions log. Engine has unit tests against synthetic weather (the
golden fixtures).

Prereqs: local Supabase stack running for DB-touching tickets (`supabase start` from repo root;
Postgres at `postgresql://postgres:postgres@127.0.0.1:54322/postgres`). Golden fixtures live in
`backend/tests/fixtures/`.

Test layout mirrors the package: `tests/engine/`, `tests/geo/`, `tests/weather/`, `tests/api/`.

**Dependency note (ordering fix from the Pre-1 adversarial review):** the numbering is *not* a strict
topological order. `T1.3` (models) defines `GeoPoint`, which `T1.2` (geo) imports in its signatures,
and `PolarTable` (in `T1.4`) is referenced by `BoatPreset` in `T1.3`'s `state.py`. Do **T1.3 before
T1.2 and T1.4** (or, if kept in number order, first land the tiny `GeoPoint`/`PolarTable` model
definitions so the imports resolve). T1.1 (client) is independent and can go anytime before T1.10.

---

### [ ] T1.1 Open-Meteo client + availability spike · Complexity: M
Files: backend/passage/weather/client.py, backend/tests/weather/test_client.py
Contract: specs/weather-cache.md §1 (sources, variables, unit conversion, spike-first + ERA5 fallback)
Do:
- `fetch(source, latitude, longitude, start_hour, end_hour) -> dict[hour_utc -> variables]` for the
  two sources `om-weather` (wind_speed_10m, wind_direction_10m, wind_gusts_10m, pressure_msl) and
  `om-marine` (wave_height). Convert all speeds to **knots**; keep wind direction (deg, from),
  pressure (hPa), wave height (m).
- Use `httpx`. Group a tile's hours into one request (`start_date`/`end_date` or `past_days`).
- Spike: a **live** smoke test (`@pytest.mark.live`, NOT run in CI) that fetches a recent-past
  window for one ocean point from both sources and asserts non-empty hourly data — this is the
  PLAN.md "verify marine past-hours availability" spike. Record findings in this ticket's note.
- CI test: use `httpx.MockTransport` with a captured/sample payload to assert parsing + unit
  conversion (m/s or km/h → kn) are correct.
Accept:
- Mock-transport test passes in CI (no network).
- Live smoke test passes locally against both endpoints for a recent-past window (note the result).
Verify: cd backend && uv run pytest tests/weather/test_client.py -q -m "not live"
Escalate if: marine past-hours are unavailable for a needed recent window (fall back to ERA5 archive
per the contract, and note it) or the recent-history endpoint behaves differently than §1 assumes
(trigger 2, contract question — consult, then update specs/weather-cache.md via a spec note).

### [x] T1.2 Geo math · Complexity: S
Files: backend/passage/geo/__init__.py, backend/passage/geo/sphere.py, backend/tests/geo/test_geo.py
Contract: specs/engine-state.md §5; specs/golden-fixtures.md GF-2
Do:
- `distance_nm`, `initial_bearing_deg`, `offset` (great-circle), all normalizing longitude to
  `[-180,180)`. Haversine with EARTH_RADIUS_NM from engine constants.
- Raise/escalate-marker for |lat| > 85° or pole-crossing offset (do not silently return garbage).
Accept:
- GF-2 table passes (meridian/equator exact; diagonal + antimeridian computed & frozen as literals).
Verify: cd backend && uv run pytest tests/geo -q
Escalate if: antimeridian or high-latitude math misbehaves (trigger 3).
Note: an endpoint-only high-latitude check on `offset` is NOT sufficient — verified numerically
that a path from 70N on a near-meridional course (bearing 10 deg) sweeping ~6000nm passes through
~86.6N (a genuine pole-crossing vertex) before landing back down around 9.7N; both endpoints look
"safe" (<=85 deg) so an endpoint-only guard would silently return garbage. Implemented a proper
mid-path check using Clairaut's relation (great-circle vertex latitude) in
`passage/geo/sphere.py::_max_abs_lat_deg_along_path`, raising `HighLatitudeError` (new, local to
this module) whenever the swept arc's vertex exceeds `HIGH_LATITUDE_LIMIT_DEG=85`. Covered by
`tests/geo/test_geo.py::TestHighLatitudeEscalation::test_offset_rejects_mid_path_pole_crossing_even_with_innocuous_endpoint`.
`distance_nm`/`initial_bearing_deg` only check their two given endpoints (no path to sweep).

### [x] T1.3 Engine state models, orders, constants, tuning · Complexity: M
Files: backend/passage/engine/__init__.py, backend/passage/engine/state.py,
  backend/passage/engine/orders.py, backend/passage/engine/constants.py,
  backend/passage/engine/tuning.py, backend/tests/engine/test_models.py
Contract: specs/engine-state.md §2/§3, specs/orders.md
Do:
- Implement all Pydantic models in §3 (GeoPoint, WeatherSample, VesselState, TrackPoint, LogEntry,
  BoatPreset, PassageParams, SegmentResult, the enums, the WeatherProvider/LandQuery Protocols) and
  the `Orders`/`SailPlan`/`RoutingMode` models per specs/orders.md.
- `constants.py` exactly as §2. `tuning.py` with the NEEDS-JUDGMENT placeholders in §8 (do not tune).
- Orders validation rules from specs/orders.md (HEADING requires fixed_heading_deg; arrival_radius ≥ 1.6).
Accept:
- Models round-trip (construct + `model_dump`/`model_validate`); validation rejects the bad cases.
Verify: cd backend && uv run pytest tests/engine/test_models.py -q
Note: real import cycle between state.py (PassageParams needs Orders) and orders.py (Orders
needs GeoPoint) — resolved via `from __future__ import annotations` + a TYPE_CHECKING-only
import of Orders in state.py, with `PassageParams.model_rebuild(_types_namespace={"Orders":
Orders})` called once in passage/engine/__init__.py after both modules load. Also landed
`PolarTable` (model only, no `boat_speed()` function yet) in polars.py ahead of T1.4, since
BoatPreset needs it directly (no cycle there) — T1.4 should extend polars.py, not recreate it.
Added `pydantic` as an explicit pyproject dependency (was previously only transitive via
pydantic-settings).

### [x] T1.4 Polars + boat presets · Complexity: M
Files: backend/passage/engine/polars.py, backend/passage/engine/boats.py, backend/tests/engine/test_polars.py
Contract: specs/engine-state.md §4; specs/golden-fixtures.md GF-1
Do:
- `PolarTable` model + `boat_speed(polar, tws_kn, twa_deg)` bilinear interpolation with clamping and
  TWA `abs`-folding exactly per §4.
- `boats.py`: a preset registry `BOAT_PRESETS: dict[str, BoatPreset]` with `cruiser35`, `perf45`,
  `cat40` as pure Python constants. Polar numbers are **NEEDS-JUDGMENT placeholders** — plausible but
  explicitly un-tuned; add a comment saying so. Include `max_hull_speed_kn` per boat.
- `get_boat(key) -> BoatPreset` raising on unknown key.
Accept:
- GF-1 table passes exactly (load `polar_test.json`).
- Every preset polar is monotonic-ish and non-negative (a light sanity test, not tuning).
Verify: cd backend && uv run pytest tests/engine/test_polars.py -q
Escalate if: you feel the need to tune polar values to make something "look right" (trigger 5 — leave
placeholders, that's a spec-session job with Steven).
Note: `boat_speed()` added to the `polars.py` T1.3 already started (bisect-based axis clamp/interp
helper `_axis_interp`, shared by both TWS and TWA). All 7 GF-1 rows pass exactly. Preset polars
(cruiser35/perf45/cat40) are hand-built placeholders shaped like real polars (rise from close-hauled,
peak around TWA 110-120, taper to dead run; wind-speed factor saturating toward each boat's
max_hull_speed_kn) — plausible-looking but explicitly NOT tuned, per the escalate-if above.

### [x] T1.5 Motion step · Complexity: M
Files: backend/passage/engine/motion.py, backend/tests/engine/test_motion.py
Contract: specs/engine-state.md §6 (steering + integration, frozen order of operations);
  specs/golden-fixtures.md GF-3, GF-4
Do:
- `step(state, ws, orders, destination, boat) -> VesselState` implementing §6 exactly: desired
  bearing → steering clamp (no-go zones, favored-tack selection, starboard tie-break) → boat speed
  (polar × wave_drag_factor) → local-tangent-plane vector sum with current → displacement → new state.
- Use start-of-step latitude for the lon divisor. Angles/units per §1.
Accept:
- GF-3 (with current) and GF-4 (no current) pass to the stated tolerances.
- An upwind case: desired bearing dead upwind ⇒ realized heading is `wind_from ± UPWIND_LIMIT` on the
  side with positive VMG toward the mark (hand-check one case).
Verify: cd backend && uv run pytest tests/engine/test_motion.py -q
Escalate if: tack selection oscillates near a layline (trigger 3 — do not add ad-hoc hysteresis).
Escalation consult (trigger 3/5, resolved): the frozen tie-break wording ("choose the starboard
option, heading obtained by turning clockwise from the wind" = `wind_from + UPWIND_LIMIT_DEG`) was
backwards — verified independently (relative-bearing derivation + classic beating-diagram check)
that `wind_from + UPWIND_LIMIT_DEG` is actually PORT tack, and `wind_from - UPWIND_LIMIT_DEG` is
starboard. Consulted an opus subagent to re-derive from scratch before touching the frozen spec a
second time; it independently confirmed the same result and derived the matching downwind-branch
formula (`reciprocal(wind_from) + (180 - DOWNWIND_LIMIT_DEG)` = starboard), noting both branches
unify to `wind_from - TWA (mod 360) = starboard`. specs/engine-state.md §6 tie-break bullet
corrected accordingly (2026-07-16). No golden fixture needed regenerating — GF-3/GF-4 are beam
reaches (TWA=90) and never exercise the tie-break; `test_motion.py::TestSteeringNoGoZones` adds
direct coverage of both the upwind and downwind tie-break cases against the corrected rule.

### [x] T1.6 Segment simulation, RNG rule, engine purity · Complexity: M
Files: backend/passage/engine/simulate.py, backend/passage/engine/rng.py,
  backend/tests/engine/test_simulate.py, backend/tests/engine/test_determinism.py,
  backend/tests/engine/test_purity.py
Contract: specs/engine-state.md §7; specs/golden-fixtures.md GF-5, GF-6, GF-7
Do:
- `simulate_segment(params, start_state, weather, land, until) -> SegmentResult` per §7: step loop,
  step-aligned assertions, per-step track points, hourly conditions log, waypoint/arrival/grounding
  handling, terminal-status stop.
- `rng.py`: `rng_for_step(seed, step_index, stream)` per the frozen RNG rule (unused in Phase 1 but
  required now).
- `test_purity.py`: import-inspect every module under `passage/engine/` and assert none import
  `httpx`, `psycopg`, `passage.db`, `passage.weather`, or `passage.api` (engine purity tripwire).
Accept:
- GF-5 (waypoint advance + arrival), GF-7 (grounding) pass.
- **GF-6 passes: 1-chunk vs 4-chunk vs 144-chunk give bit-identical tracks and end_state.**
- Purity test passes.
Verify: cd backend && uv run pytest tests/engine -q
Escalate if: GF-6 ever fails (trigger 1 — STOP, do not weaken `==`).
Note: GF-6 passed bit-identical on the first run (1-chunk == 4-chunk == 144-chunk, both
TrackPoints and end_state) — no escalation needed. `simulate_segment`'s `_active_target` helper
special-cases HEADING mode to always check arrival against `destination` (never
`orders.waypoints`), since orders.md says HEADING mode ignores waypoints entirely; using
`orders.waypoints` unconditionally would have been wrong whenever a HEADING-mode passage happened
to carry a stale/irrelevant waypoints list.
Known limitation (not a determinism risk, flagged for visibility): the "conditions" log's
`distance_run_nm` (data payload, "distance run this hour") is accumulated locally within a single
`simulate_segment` call and resets to 0 at the start of each call. Real catch-up chunks are only
step-aligned, not hour-aligned (`sim_target` depends on wall-clock "now" at check-in), so in
practice almost every check-in's first post-boundary conditions entry will under-report the true
hourly distance by the portion simulated in the previous call. This does NOT affect
TrackPoint/end_state (GF-6 unaffected, verified: GF-6 intentionally does not compare log_entries
across chunk variants) and VesselState has no field to carry a chunk-invariant hourly accumulator
without a contract change — fixing this properly would mean adding a field to VesselState, which
is out of this ticket's scope. Flagging for Pre-2 gate awareness, not escalating now.

### [ ] T1.7 Weather cache access + pure sampler · Complexity: M
Files: backend/passage/weather/cache.py, backend/passage/weather/sampler.py,
  backend/tests/weather/test_cache.py, backend/tests/weather/test_sampler.py
Contract: specs/weather-cache.md §2–§4; specs/golden-fixtures.md GF-8
Do:
- `cache.py`: tile snapping (integer indices per §2), `read_rows`/`insert_rows` against
  `weather_cache` via `passage.db.get_connection`, insert with `ON CONFLICT DO NOTHING` (never
  overwrite), and `prune_passage_weather(conn, passage_id)`.
- `sampler.py`: `build_sampler(rows) -> WeatherProvider` doing trilinear interpolation (bilinear
  space + linear time), **angles as unit vectors**, merging `om-weather` + `om-marine`, `current_*`=0,
  raising on missing tiles/hours (no extrapolation).
- (Prefetch/box logic that calls the T1.1 client lives in the API orchestration T1.10; here just the
  cache table access + the pure sampler over given rows.)
Accept:
- GF-8 passes (center value 18.0; angle-wrap midpoint 0/360; missing-tile raises).
- Cache never-overwrite: inserting a changed value for an existing key leaves the original (test).
Verify: cd backend && uv run pytest tests/weather -q -m "not live"   (needs local Supabase up)
Escalate if: interpolation artifacts at tile/hour boundaries (trigger 3).

### [ ] T1.8 Passage/track/log repository · Complexity: M
Files: backend/passage/db/passages.py, backend/passage/db/track.py, backend/tests/db/test_repository.py
Contract: specs/engine-state.md §3 (VesselState is the authoritative resume state on the passage row);
  migration 20260715120000
Do:
- psycopg CRUD (plain SQL, no ORM): create passage, get passage, list passages, update orders,
  persist a catch-up result (append track points + log entries with monotonic `seq`, update the
  denormalized VesselState + `last_simulated_at` on the passage row) — ideally in one transaction.
- Map rows ↔ Pydantic models. Store `orders` as jsonb (`model_dump`), reload via `model_validate`.
Accept:
- Round-trip a passage; append two catch-up batches and confirm seqs are contiguous and the passage
  row's current state equals the last track point.
Verify: cd backend && uv run pytest tests/db -q   (needs local Supabase up)

### [ ] T1.9 Land mask (grounding) · Complexity: M
Files: backend/passage/geo/land.py, backend/tests/geo/test_land.py
Contract: specs/engine-state.md §3 (LandQuery), §7 (grounding); PLAN.md land-mask risk note
Do:
- Provide a `LandQuery` implementation `is_water(lat, lon) -> bool` backed by a **coarse** global
  land/sea dataset, loaded once outside the engine (this module may do I/O; the engine only sees the
  callable). Implementation may use a lightweight lib (e.g. `global-land-mask`) or a small bundled
  packed raster — your choice, but keep it deterministic and cheap to query.
- Accuracy is **coarse / NEEDS-JUDGMENT**; high-resolution coastal accuracy is explicitly Phase 6.
  Document the resolution in the module docstring.
Accept:
- Known-ocean points (mid-Atlantic, mid-Pacific) → water; known-land points (Kansas, Sahara) → not
  water. A handful of hand-picked assertions.
Verify: cd backend && uv run pytest tests/geo/test_land.py -q
Escalate if: the dependency/dataset would blow the Vercel function size budget (trigger 2/4 — this
ticket is deferrable; if it can't be done cleanly, stop and note it under ## Blocked, and the engine
still works with an always-water stub since grounding just never fires).

### [ ] T1.10 Passage API + chunked catch-up orchestration · Complexity: M
Files: backend/passage/api/passages.py, backend/passage/main.py (mount router),
  backend/passage/config.py (add max_catchup field), backend/passage/weather/prefetch.py,
  backend/tests/api/test_passages.py, .env.example, specs/api-skeleton.md (Settings table)
Contract: specs/engine-state.md §7 (chunked catch-up — the frozen orchestration rules), §9 (Settings);
  specs/weather-cache.md §4 (prefetch/box)
Do:
- Add `max_catchup_hours_per_request: int = 6` to Settings (env `PASSAGE_MAX_CATCHUP_HOURS_PER_REQUEST`);
  update .env.example and the specs/api-skeleton.md Settings table (this is the sanctioned contract edit).
- `prefetch.py`: given a chunk `[t0,t1]` and start position, compute the tile box + hour span, fetch
  missing rows via the T1.1 client into the cache, and `build_sampler` over the needed rows.
- Endpoints under the authed `/api` router:
  - `POST /api/passages` — create (origin, destination, boat_key, orders, optional `started_at`
    defaulting to now and required `<= now`, optional name/seed/module_toggles/difficulty). Emit the
    one-time `departure` log entry at k=0. Return the passage + initial state.
  - `GET /api/passages`, `GET /api/passages/{id}`, `GET /api/passages/{id}/track`,
    `GET /api/passages/{id}/log`, `PUT /api/passages/{id}/orders`.
  - `POST /api/passages/{id}/checkin` — read `now = datetime.now(UTC)` once; compute step-aligned
    `sim_target` and `chunk_end` per §7; prefetch weather; `simulate_segment`; persist via T1.8;
    return `{caught_up, state, new_track_points, new_log_entries}`.
- Time/clock lives ONLY here, never in the engine.
Accept:
- Create → checkin loop drives the boat; `caught_up` flips true when `end_state.time` reaches the
  step-aligned target; terminal status stops it. Tests may inject a fake `now` and a stub/mock
  weather client (no live network in CI).
- **Chunk-invariance THROUGH the DB (not just in-memory GF-6):** with the same stub weather, catch a
  passage up in one big chunk vs many small chunks (e.g. `max_catchup_hours_per_request` = large vs
  = STEP) and assert the persisted track points + end state are bit-identical. This is the test GF-6
  cannot cover, because it exercises the `VesselState` round-trip through `double precision` columns.
  If it diverges, the float round-trip is lossy — use psycopg binary params or store enough precision;
  do NOT weaken to `approx` (trigger 1).
- 401s still enforced (endpoints under the authed router).
Verify: cd backend && uv run pytest tests/api -q   (needs local Supabase up)
Escalate if: chunked vs single-shot catch-up produce different tracks in an integration test
(trigger 1 — the engine is fine per GF-6, so a diff here means the orchestration violated step
alignment; fix the orchestration, never the engine assertion).

### [ ] T1.11 End-to-end exit-criterion test + prod migration · Complexity: M
Files: backend/tests/api/test_e2e_catchup.py, (deploy step: supabase db push)
Contract: all of the above; PLAN.md Phase 1 exit
Do:
- Integration test using a stub weather client seeded with a synthetic-but-realistic hourly field
  (deterministic), a real local DB, and an injected `now`: create a passage with `started_at = now −
  12h`, then call `checkin` repeatedly until `caught_up`. Assert: a believable track (monotonic time,
  positions advance toward the destination, plausible speeds), ~12 hourly `conditions` log entries,
  a `departure` entry, and that running the whole thing again yields an identical track (determinism
  through the full stack).
- Push the Phase-1 migration to production Supabase (`supabase db push`) — coordinate with Steven;
  this is the one deploy-touching step. Verify `/health` still green and a create+checkin works
  against the deployed backend (smoke).
Accept:
- E2E test passes locally; the deployed backend can create a passage and check in over HTTPS.
Verify: cd backend && uv run pytest tests/api/test_e2e_catchup.py -q   (needs local Supabase up)
Escalate if: the full-stack replay differs from the first run (trigger 1).

---

## Notes carried from the Pre-1 gate (context, not tickets)

- **Scope call (flag to Steven):** two Phase-1 inclusions are judgment calls the spec session made to
  keep the exit criterion ("believable track") honest: (1) a **minimal deterministic beating/running
  rule** so upwind/downwind legs don't stall or look absurd — simplest possible (fixed close-hauled/
  running angles, favored-tack pick), full tactical routing is later; (2) a **coarse land mask** for
  grounding, high-res coastal accuracy deferred to Phase 6 as PLAN.md already planned. Both are marked
  NEEDS-JUDGMENT where values are involved.
- **Deferred to their gates:** sail-plan performance & reef granularity (Pre-3), conditional standing
  orders (Pre-3), events/damage/resources/crew (Phase 5), real ocean currents & tides (Phase 6 — the
  current-set *math* is built and tested now with synthetic current), GRIB tools (Phase 4), replay UI
  & routing baseline (Phase 7).
- **Watch items for the Pre-2 gate:** the check-in *response shape* here is functional (enough to
  demo via curl and drive tests); Pre-2 formalizes the payloads the frontend consumes and the
  component map. Order-change *history* is not stored yet (only current orders on the passage row) —
  Phase 7 replay across order changes will need it; flagged now.
- **T1.6 finding, carried forward:** the hourly "conditions" log's `distance_run_nm` under-reports
  after a catch-up chunk boundary splits an hour (see T1.6's note above) because `VesselState` has
  no field to carry a chunk-invariant "distance since last conditions log" across calls. Not a
  determinism risk (track/end_state unaffected), just a narrative-log imprecision that's actually
  the common case in production (check-ins land at arbitrary times). If it matters enough to fix
  properly, the fix is a `VesselState` contract change (e.g. an added field) — a spec-session
  decision, not an implementation-session one.
