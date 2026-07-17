# CONTRACT: Weather Cache & Sampling (Phase 1)

Frozen by the Pre-1 spec session (2026-07-15). Defines how the boat's ground-truth weather is
fetched from Open-Meteo, cached in Supabase Postgres, and turned into the pure `WeatherProvider`
the engine consumes. Companion: `specs/engine-state.md`, `specs/deployment.md`.

Two jobs: **(1) determinism** — a catch-up replayed later must see byte-identical weather, so
responses are cached and **never overwritten**; **(2) volume/latency** — batch fetches by tile and
hour, cache aggressively (a 12 h catch-up is a handful of requests, not 72).

The `weather/` package does I/O (`httpx`, `psycopg`). The engine does not: the weather layer builds
a **pure** sampler over already-fetched data and hands it in. This is the seam that keeps
`engine/` pure.

---

## 1. Data source (Open-Meteo)

Phase-1 variables (from PLAN.md): wind speed, wind direction, gusts, pressure, wave height. Split
across two Open-Meteo endpoints, distinguished by the cache `source` column:

| `source` | Endpoint | Variables (Open-Meteo names) | Engine field (converted) |
|---|---|---|---|
| `om-weather` | Forecast API (`api.open-meteo.com/v1/forecast`, with `past_days` for recent history) | `wind_speed_10m`, `wind_direction_10m`, `wind_gusts_10m`, `pressure_msl` | `wind_speed_kn`, `wind_dir_deg`, `gust_kn`, `pressure_hpa` |
| `om-marine` | Marine API (`marine-api.open-meteo.com/v1/marine`) | `wave_height` | `wave_height_m` |

- Request `windspeed_unit=kn` where supported; otherwise convert to knots in the client. Wind
  direction is already "from", degrees — matches our convention. **Convert all speeds to knots
  before storing** so the cache holds engine-ready units.
- `current_speed_kn` / `current_dir_deg`: **not fetched in Phase 1** (real ocean currents are Pre-6).
  The sampler returns `0.0` for both. The engine's current-set math is exercised by golden fixtures
  with synthetic current, not by live data.
- **Spike first (see T1.1).** Marine past-hours availability and the exact recent-history endpoint
  behaviour must be verified against the live API before building on them. If marine past-hours are
  unavailable for a needed window, fall back to the ERA5 archive endpoint
  (`archive-api.open-meteo.com`) — this is a documented contract fallback (PLAN.md risks). If the
  wind/pressure past-hours story also fails, escalate (trigger 2, contract question).

---

## 2. Tiling & time (frozen — these define cache keys)

- **Spatial snapping.** Positions are snapped to a grid of `TILE_RESOLUTION_DEG = 0.25°`
  (`specs/engine-state.md` constants). Integer tile indices, not raw floats, are the key:
  - `lat_idx = round((lat + 90.0) / TILE_RESOLUTION_DEG)`
  - `lon_idx = round((lon + 180.0) / TILE_RESOLUTION_DEG)`
  - snapped `latitude = lat_idx * TILE_RESOLUTION_DEG - 90.0`, `longitude = lon_idx * TILE_RESOLUTION_DEG - 180.0`.
  Integer indices avoid float-equality hazards in the primary key.
- **Temporal snapping.** Source resolution is hourly. `hour_utc` is the sample's UTC hour, truncated
  (`minute=second=microsecond=0`).
- Changing `TILE_RESOLUTION_DEG` changes every key and invalidates all caches — it is a frozen
  determinism constant, not tuning.

---

## 3. Cache table (in the Phase-1 migration)

```sql
-- CONTRACT (see the Phase-1 migration for the authoritative DDL)
create table weather_cache (
    passage_id  uuid        not null references passage(id) on delete cascade,
    source      text        not null,      -- 'om-weather' | 'om-marine'
    lat_idx     integer     not null,      -- snapped tile index (section 2)
    lon_idx     integer     not null,
    hour_utc    timestamptz not null,      -- truncated to the hour
    latitude    double precision not null, -- snapped tile lat (for the API request / debugging)
    longitude   double precision not null, -- snapped tile lon
    variables   jsonb       not null,      -- engine-ready values in knots/hPa/m, keys = engine fields present for this source
    fetched_at  timestamptz not null,
    primary key (passage_id, source, lat_idx, lon_idx, hour_utc)
);
```

- **Per-passage scoping (frozen decision).** The cache key includes `passage_id`. Rationale: this is
  a single-user app with rarely more than one active passage; per-passage scoping makes determinism
  airtight (a passage's replay only ever reads rows it wrote), makes pruning trivial (`delete where
  passage_id = ...`), and the cost (a second passage re-fetching a shared tile) is negligible at this
  scale. Do **not** share cache rows across passages.
- **Never overwrite (frozen).** Inserts use `ON CONFLICT (passage_id, source, lat_idx, lon_idx,
  hour_utc) DO NOTHING`. The first value fetched for a (tile, hour) is frozen for that passage
  forever. This is what makes even recent/still-revising hours deterministic across replays.

---

## 4. Prefetch, fetch, and the pure sampler

Catch-up for a chunk `[t0, t1]` (both step-aligned) proceeds:

1. **Bounding box.** Compute a lat/lon box that generously covers where the boat can be during the
   chunk: start from `start_state.position`, pad by `v_max * (t1 - t0)` converted to degrees, plus one
   tile of margin on each side, where `v_max` is an upper bound on **SOG**, not hull speed — use
   `max_hull_speed_kn` **plus** the max plausible current (0 for Phase-1 real data, but nonzero once
   Phase 6 currents arrive). Convert nm→degrees **per axis**: `dlat_deg = nm/60`,
   `dlon_deg = nm/(60·cos(lat))` (longitude degrees shrink with latitude; using `nm/60` for longitude
   under-covers the box at mid/high latitude and the boat can escape it). (A chunk is ≤
   `max_catchup_hours_per_request`, so the box is small.) Enumerate all tile indices in the box.
2. **Hours.** Enumerate every UTC hour spanning `[t0 - 1h, t1 + 1h]` (±1h so temporal interpolation
   at the ends has both bracketing hours).
3. **Cache-first fetch.** For each `(source, tile, hour)` not already present for this passage, batch
   requests to Open-Meteo (one request can cover many hours for a tile; group by tile). Convert units,
   insert `ON CONFLICT DO NOTHING`. Rows already present are reused untouched.
4. **Build the sampler.** Load all needed rows for the box+hours into memory and return a pure
   `WeatherProvider` closure. No further I/O happens during stepping.

**Sampler interpolation (frozen):** given a query `(lat, lon, time)`:
- Find the 4 surrounding tiles (`lat_idx`/`lat_idx+1` × `lon_idx`/`lon_idx+1`) and the 2 bracketing
  hours. Do **bilinear** interpolation in space and **linear** interpolation in time =
  **trilinear** overall, per variable.
- **Angles** (`wind_dir_deg`) are interpolated as unit vectors (interpolate `sin`/`cos`, then
  `atan2`), never as raw degrees (to avoid the 359°→1° wrap bug).
- Merge `om-weather` and `om-marine` variables into one `WeatherSample`. `current_*` = 0.
- If a tile/hour needed for interpolation is missing (box too small / boat left the box), that is a
  prefetch bug — the caller must widen the box and refetch, not silently extrapolate. The sampler
  raises rather than guessing. (Escalate if this recurs — trigger 3, interpolation/box boundary.)

The sampler is a pure function of the in-memory rows: identical rows ⇒ identical samples ⇒
deterministic. Golden fixture GF-8 pins the trilinear math to hand-computed values.

---

## 5. Pruning (Supabase 500 MB budget)

- A single passage's cache is bounded but not tiny. Rows are per `(source, tile, hour)` and the
  prefetch box enumerates *all* tiles in the box × *all* hours in the chunk, not just the tiles the
  track touches. A 10-day passage is closer to **~30–50k rows** (≈ box-tiles × hours × 2 sources),
  which at small jsonb + PK/index overhead is **~10–20 MB per passage**, not "single-digit MB". That
  still fits the 500 MB free tier comfortably for a single user — but note the policy below **keeps
  arrived passages** (for the Phase-7 debrief), so retained passages accumulate: on the order of a few
  dozen completed 10-day passages would approach the budget. Pruning is a safety valve, not a hot
  path, but a manual "archive/prune old passages" affordance will be wanted before the count gets high.
- **Mechanism (frozen):** `passage/db/…` provides `prune_passage_weather(conn, passage_id)` =
  `delete from weather_cache where passage_id = %s`. Deleting a passage row cascades the same way
  (`on delete cascade`).
- **Policy (frozen):** do **not** prune automatically on `ARRIVED` — the Phase-7 debrief/replay needs
  the cache to re-run the passage. Prune only when the user deletes/archives a passage. (Archive as a
  distinct state is Phase 7; for Phase 1, pruning happens on passage delete via cascade.)

---

## 6. Determinism checklist (why this is safe)

- Same `(passage, tile, hour)` ⇒ same stored bytes (never overwritten) ⇒ same sample.
- Integer tile keys ⇒ no float-equality drift in lookups.
- Angle interpolation via vectors ⇒ no wrap discontinuity.
- Sampler is pure over in-memory rows ⇒ no clock/network inside stepping.
- Per-passage scoping ⇒ a replay reads exactly the rows the original run wrote.

**Scope of the guarantee (be honest about it).** "Never overwrite" makes **replay** fully
deterministic (a re-run reads only already-cached rows). It does **not** by itself make the *first*
catch-up chunk-invariant if the chunks are fetched at different real times: Open-Meteo revises recent
hours, so a `(tile, hour)` first fetched during a later chunk can hold a *revised* value that a single
big-chunk fetch (done earlier) would not have seen. In practice a client's catch-up requests run
back-to-back (seconds apart), so the window is tiny — but it is not provably zero. To close it, the
orchestration SHOULD, on the first catch-up of a passage, fetch the full hour span the whole catch-up
will need up front (fetching is a handful of cheap requests; only the *stepping* is chunked for the
Vercel timeout). GF-6 does **not** cover this (it uses an analytic provider, no cache/network); the
DB-round-trip chunk-invariance test lives in T1.10.
