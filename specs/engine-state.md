# CONTRACT: Engine State Model & Simulation Core (Phase 1)

Frozen by the Pre-1 spec session (2026-07-15). This is the spine of the whole project: the pure,
deterministic simulation core. Everything here is a frozen interface. Companion contracts:
`specs/orders.md`, `specs/weather-cache.md`, `specs/golden-fixtures.md`.

The overriding rules from CLAUDE.md apply with force here: **`passage/engine/` is pure** (no
`httpx`, `psycopg`, `passage.db`, no clock reads, no `Math.random`/unseeded RNG, no file/network
I/O) and **determinism is sacred** (the replay test is a tripwire, never to be loosened).

---

## 1. Units & conventions (frozen — ambiguity here silently corrupts tracks)

| Quantity | Unit | Convention |
|---|---|---|
| Latitude | degrees | `[-90, 90]`, north positive |
| Longitude | degrees | `[-180, 180)`, east positive; normalize on wrap (antimeridian) |
| Distance | nautical miles (nm) | 1° latitude = 60 nm exactly |
| Speed | knots (kn) | nm per hour |
| Bearing / heading / course | degrees | `[0, 360)`, compass: 0 = N, 90 = E, clockwise |
| Wind direction (TWD) | degrees | direction wind blows **FROM** (meteorological; matches Open-Meteo) |
| Current direction | degrees | direction current flows **TOWARD** (oceanographic) — **opposite convention to wind; classic bug source** |
| Wave direction | degrees | direction waves come **FROM** (not used in Phase 1 motion) |
| Wind/current/boat speed | knots | Open-Meteo returns m/s or km/h; the weather layer converts to knots before the engine sees it |
| Pressure | hPa | |
| Wave height | metres | significant wave height |
| Time | `datetime` | timezone-aware UTC everywhere; never naive |
| TWA (true wind angle) | degrees | `[0, 180]`, 0 = dead upwind, 180 = dead downwind; port/starboard symmetric in Phase 1 |

All times are UTC and timezone-aware. A naive datetime anywhere in the engine is a bug.

---

## 2. Frozen constants (`passage/engine/constants.py`)

Changing any of these changes cache keys and/or step sequences and therefore **breaks determinism
and invalidates existing passages** — treat as immutable contract, not tuning.

```python
# CONTRACT
from datetime import timedelta

STEP: timedelta = timedelta(minutes=10)   # integration step; also the track-point cadence
TILE_RESOLUTION_DEG: float = 0.25          # weather tile snapping grid (see specs/weather-cache.md)
NM_PER_DEGREE_LAT: float = 60.0
EARTH_RADIUS_NM: float = 3437.7468         # = 60*180/pi, so 1° = 60 nm exactly (matches NM_PER_DEGREE_LAT and §1); haversine dist/bearing
CONDITIONS_LOG_EVERY_STEPS: int = 6        # one "conditions" log entry per hour (6 × 10 min)
```

NEEDS-JUDGMENT tuning lives separately in `passage/engine/tuning.py` (section 8); do not conflate.

---

## 3. Core models (`passage/engine/state.py`)

All Pydantic v2 `BaseModel`. Models are pure data (allowed in `engine/`).

```python
# CONTRACT
from datetime import datetime
from enum import Enum
from typing import Protocol
from pydantic import BaseModel, Field


class GeoPoint(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, lt=180)


class PassageStatus(str, Enum):
    ACTIVE = "active"
    ARRIVED = "arrived"
    GROUNDED = "grounded"
    # Phase 5 adds: ABANDONED, LOST, RETIRED. Keep additive.


class WeatherSample(BaseModel):
    # The weather the boat experiences at one position and instant. Produced by the pure
    # sampler the weather layer hands to the engine (see specs/weather-cache.md). Speeds in knots.
    wind_speed_kn: float          # TWS, sustained
    wind_dir_deg: float           # TWD, direction FROM, [0,360)
    gust_kn: float
    pressure_hpa: float
    wave_height_m: float
    current_speed_kn: float = 0.0     # 0 from Phase-1 real data; nonzero in golden fixtures & Phase 6
    current_dir_deg: float = 0.0      # direction flowing TOWARD, [0,360)


class VesselState(BaseModel):
    # The dynamic state that carries between steps. This is the authoritative resume state:
    # the passage row persists exactly this (denormalized) and each catch-up resumes from it.
    time: datetime                    # simulated UTC timestamp; always started_at + k*STEP
    position: GeoPoint
    heading_deg: float                # course steered on the step that produced this state (COG)
    speed_kn: float                   # SOG on that step
    active_waypoint_index: int = 0
    distance_run_nm: float = 0.0
    status: PassageStatus = PassageStatus.ACTIVE


class TrackPoint(BaseModel):
    # One per step (10 min). Feeds the map line + instruments panel. seq assigned by the caller.
    time: datetime
    position: GeoPoint
    heading_deg: float
    speed_kn: float
    tws_kn: float
    twd_deg: float
    gust_kn: float
    pressure_hpa: float
    wave_height_m: float


class LogCategory(str, Enum):
    DEPARTURE = "departure"
    CONDITIONS = "conditions"     # hourly conditions summary
    WAYPOINT = "waypoint"
    ARRIVAL = "arrival"
    GROUNDING = "grounding"
    # Phase 5 adds: EVENT, DAMAGE, RESOURCE, etc. Keep additive.


class LogEntry(BaseModel):
    time: datetime
    category: LogCategory
    message: str                  # plain factual text in Phase 1; narrative voice is Pre-5
    data: dict = Field(default_factory=dict)   # structured payload (jsonb in DB)


class BoatPreset(BaseModel):
    key: str
    name: str
    hull_length_m: float
    max_hull_speed_kn: float      # used for the arrival-radius sanity rule
    polar: "PolarTable"           # see section 4


class PassageParams(BaseModel):
    # Static inputs for a segment. Assembled by the caller from the passage row + boat registry.
    boat: BoatPreset
    orders: "Orders"              # from specs/orders.md
    destination: GeoPoint
    seed: int
    started_at: datetime          # sim-clock origin; step_index = round((t - started_at)/STEP)


class SegmentResult(BaseModel):
    end_state: VesselState
    track_points: list[TrackPoint]
    log_entries: list[LogEntry]


class WeatherProvider(Protocol):
    # Pure sampler handed in by the weather layer. Does trilinear (space) + linear (time)
    # interpolation over already-fetched, cached tile data. No I/O inside the engine call.
    def __call__(self, lat: float, lon: float, time: datetime) -> WeatherSample: ...


class LandQuery(Protocol):
    def is_water(self, lat: float, lon: float) -> bool: ...
```

---

## 4. Polars (`passage/engine/polars.py`)

```python
# CONTRACT
class PolarTable(BaseModel):
    tws_values: list[float]                 # ascending TWS breakpoints (kn), columns
    twa_values: list[float]                 # ascending TWA breakpoints (deg, 0..180), rows
    boat_speed: list[list[float]]           # boat_speed[twa_idx][tws_idx] = BSP (kn)

def boat_speed(polar: PolarTable, tws_kn: float, twa_deg: float) -> float: ...
```

`boat_speed` interpolation (frozen):
- **Bilinear** interpolation in (TWS, TWA) between the four surrounding grid values.
- TWA is folded to `[0, 180]` via `abs` of the signed angle before lookup (port/starboard symmetric).
- Below `tws_values[0]` or below `twa_values[0]`: clamp to the nearest edge value **except** in the
  no-go zone (handled by steering, section 6 — the engine never asks the polar for an infeasible TWA
  because steering clamps the heading first).
- Above `tws_values[-1]` / `twa_values[-1]`: clamp to the last value (no extrapolation).

Polar data for the boat presets lives in `passage/engine/boats.py` as pure Python constants
(a small preset registry: `cruiser35`, `perf45`, `cat40`). **All polar numbers are NEEDS-JUDGMENT
placeholders** — structure frozen, values tuned later with Steven. See section 8.

---

## 5. Geo math (`passage/geo/`)

Pure functions (`passage/geo/rhumb.py` or `great_circle.py`):

```python
# CONTRACT
def distance_nm(a: GeoPoint, b: GeoPoint) -> float: ...        # great-circle (haversine)
def initial_bearing_deg(a: GeoPoint, b: GeoPoint) -> float: ...# great-circle initial bearing a->b, [0,360)
def offset(point: GeoPoint, bearing_deg: float, distance_nm: float) -> GeoPoint: ...  # move along great circle
```

- `offset` and all lon arithmetic **normalize longitude to `[-180, 180)`** (antimeridian safe).
- Haversine is used for `distance_nm` and `initial_bearing_deg`.
- **Per-step displacement, however, uses the local-tangent-plane method (section 6), not `offset`.**
  `offset` is used for longer hops if needed and in tests; the step integrator uses the flat-plane
  form so golden outcomes are exactly hand-computable.
- High latitude (|lat| > 85°) or a step that would cross a pole: escalate (trigger 3). Phase-1
  passages are temperate/tropical ocean; polar routing is out of scope.

---

## 6. Motion & steering (`passage/engine/motion.py`)

One step advances the vessel by exactly `STEP`. All pure. Order of operations is frozen (it affects
floating-point results and therefore determinism):

**Per step, given `state`, `WeatherSample ws` sampled at `(state.position, state.time)`, `orders`,
`destination`, `boat`:**

1. **Desired bearing.**
   - WAYPOINT mode: `desired = initial_bearing_deg(position, target)` where `target =
     waypoints[active_waypoint_index]` (or `destination` if waypoints empty).
   - HEADING mode: `desired = orders.fixed_heading_deg`.
2. **Steering clamp (no-go zones).** Compute the TWA the desired bearing implies:
   `twa_desired = angular_diff(desired, ws.wind_dir_deg)` folded to `[0,180]`.
   (TWA is the angle between the heading and the wind **source** = `wind_dir_deg` (FROM), per §1:
   0 = dead upwind, 180 = dead downwind. Do **not** use `reciprocal(wind_dir_deg)` here — that
   inverts upwind and downwind. Note the downwind branch below still uses `reciprocal(wind_from)`
   for its *feasible headings*, which is correct.)
   - If `UPWIND_LIMIT_DEG <= twa_desired <= DOWNWIND_LIMIT_DEG`: `heading = desired`.
   - If `twa_desired < UPWIND_LIMIT_DEG` (pinching): sail close-hauled. The two feasible headings
     are `wind_from ± UPWIND_LIMIT_DEG` (where `wind_from = ws.wind_dir_deg`). Choose the one with
     the **smaller angular distance to `desired`** (the favored tack). `heading =` that.
   - If `twa_desired > DOWNWIND_LIMIT_DEG` (dead downwind): the two feasible headings are
     `reciprocal(wind_from) ± (180 - DOWNWIND_LIMIT_DEG)`. Choose the one closer to `desired`.
   - Tie-break (exactly equal angular distance): choose the **starboard-tack** heading (wind on the
     starboard side), for reproducibility. Starboard tack is always `wind_from - TWA` (mod 360) — the
     *counter-clockwise* side of the wind source (compass 0 = N, clockwise-positive, `wind_from` =
     direction the wind blows FROM; verified by relative-bearing derivation and against the classic
     beating-to-windward diagram: wind from due north, starboard tack points NW, i.e.
     `wind_from - close_hauled_angle`). Concretely per branch:
     - upwind branch: starboard = `wind_from - UPWIND_LIMIT_DEG` (port = `wind_from + UPWIND_LIMIT_DEG`).
     - downwind branch: starboard = `reciprocal(wind_from) + (180 - DOWNWIND_LIMIT_DEG)` (port =
       `reciprocal(wind_from) - (180 - DOWNWIND_LIMIT_DEG)`); this is algebraically the same rule,
       since `reciprocal(wind_from) + (180 - DOWNWIND_LIMIT_DEG) ≡ wind_from - DOWNWIND_LIMIT_DEG`
       (mod 360).
     This tie-break is frozen for determinism. (Pre-1 gate review note: the previous wording —
     "turning clockwise from the wind" = `wind_from + UPWIND_LIMIT_DEG` — was backwards; that
     arithmetic is port tack, not starboard. Fixed 2026-07-16, confirmed by independent derivation.)
   - `UPWIND_LIMIT_DEG`, `DOWNWIND_LIMIT_DEG` are NEEDS-JUDGMENT (section 8). Tack/gybe selection is
     recomputed each step; because the favored side only flips when `desired` crosses the wind axis,
     this yields natural tacking without per-step jitter. If oscillation is observed near a layline,
     escalate (trigger 3) — do not add ad-hoc hysteresis without a spec decision.
3. **Boat speed through the water.** `bsp = boat_speed(boat.polar, ws.wind_speed_kn, twa_realized)`
   where `twa_realized` is the TWA of the clamped `heading`. Apply NEEDS-JUDGMENT modifiers
   (section 8): `bsp *= wave_drag_factor(ws.wave_height_m)`. (Leeway default 0 in Phase 1.)
4. **Velocity vectors (local tangent plane, knots → N/E components).**
   - Boat-through-water: `(vN_b, vE_b) = (bsp*cos(heading), bsp*sin(heading))`.
   - Current (flows TOWARD `current_dir_deg`): `(vN_c, vE_c) = (cur*cos(dir), cur*sin(dir))`.
   - Resultant `(vN, vE) = (vN_b + vN_c, vE_b + vE_c)`.
   - `sog = hypot(vN, vE)`; `cog = atan2(vE, vN)` normalized to `[0,360)`.
5. **Displacement over STEP** (`dt_hours = STEP.total_seconds()/3600`):
   - `dN_nm = vN * dt_hours`, `dE_nm = vE * dt_hours`.
   - `new_lat = lat + dN_nm / NM_PER_DEGREE_LAT`.
   - `new_lon = normalize_lon(lon + dE_nm / (NM_PER_DEGREE_LAT * cos(radians(lat))))`.
     (Use the **start-of-step** `lat` for the cos factor — frozen, for reproducibility.)
6. New `VesselState`: `time += STEP`, `position = (new_lat, new_lon)`, `heading_deg = cog`,
   `speed_kn = sog`, `distance_run_nm += sog * dt_hours`.

`cos(radians(lat))` at |lat| near 90 → division blow-up; guarded by the section-5 high-latitude rule.

---

## 7. Segment simulation & catch-up mechanics (`passage/engine/simulate.py`)

```python
# CONTRACT
def simulate_segment(
    params: PassageParams,
    start_state: VesselState,
    weather: WeatherProvider,
    land: LandQuery,
    until: datetime,            # step-aligned target; see below
) -> SegmentResult: ...
```

**Stepping loop (frozen):**
- Let `k0 = round((start_state.time - params.started_at) / STEP)`. Assert
  `start_state.time == params.started_at + k0*STEP` (state is always step-aligned).
- While `state.time < until` and `state.status == ACTIVE`:
  - Sample `ws = weather(state.position.lat, state.position.lon, state.time)`.
  - Advance one step (section 6) → `next_state` at `state.time + STEP`, step index `k = k0 + (#steps done) + 1`.
  - **Grounding check:** if `not land.is_water(next_state.position...)` → set `status = GROUNDED`,
    emit a `grounding` log entry at `next_state.time`, append the track point, **stop**.
  - **Arrival / waypoint check** (at the new position): if within `arrival_radius_nm` of the active
    target: if it's the last waypoint (or `destination`), set `status = ARRIVED`, emit `arrival`,
    append track point, **stop**; otherwise emit `waypoint`, increment `active_waypoint_index`.
  - Append a `TrackPoint` every step.
  - Emit a `conditions` `LogEntry` when the new step index `k % CONDITIONS_LOG_EVERY_STEPS == 0`
    (i.e., on the hour), summarizing position/wind/waves/distance-run-this-hour.
- Return `SegmentResult(end_state=state, track_points=..., log_entries=...)`.

**`until` MUST be step-aligned** and is the caller's responsibility (section below). The engine may
assert it. The departure (`k == 0`) `departure` log entry is emitted once, by the caller at passage
creation (not inside `simulate_segment`), so re-entrant segments don't duplicate it.

### Chunked catch-up (the deployment constraint, frozen)

The orchestration lives in the API layer (`passage/api/passages.py`) — **not** the engine — because
it reads the clock and does I/O. It MUST obey:

- Read `now = datetime.now(UTC)` **once** at the request boundary. The engine never reads the clock.
- Target sim-time = the largest step boundary `<= now`: `k_now = floor((now - started_at)/STEP)`,
  `sim_target = started_at + k_now*STEP`. **Never simulate a partial trailing step** — this is what
  makes the result independent of *when* you check in (chunk-invariance / replay identity). The boat
  therefore always lags real time by `< STEP`.
- Per request, simulate at most `settings.max_catchup_hours_per_request` of sim-time:
  `chunk_end = min(sim_target, state.time + max_catchup)` **snapped down to a step boundary**.
- Call `simulate_segment(..., until=chunk_end)`, persist the new track points/log entries and the
  new authoritative `VesselState` onto the passage row (`last_simulated_at = end_state.time`).
- Return `caught_up = (end_state.time >= sim_target) or (status is terminal)`. The client re-calls
  check-in until `caught_up` is true.

**Chunk boundaries never change outcomes.** Because (a) every boundary is a step boundary, (b) the
per-step computation depends only on `(state_at_step_start, weather_at_that_step)`, and (c) weather
is served from a never-overwrite per-passage cache, simulating `[0,24h]` in one call, or four 6h
calls, or 144 ten-minute calls, all produce **bit-identical** track points. This is the sacred
replay invariant (golden fixture GF-6). If it ever fails, that is an automatic escalation
(trigger 1) — never "fix" it by loosening the assertion to approximate equality.

### RNG rule (frozen now, unused in Phase 1)

Phase-1 motion is fully deterministic (no random draws). But so that Phase 5 events cannot break
chunk-invariance, freeze the rule now: **any stochastic draw at step index `k` must derive its
randomness from a substream keyed by `(seed, k, stream_name)`** — e.g.
`Random(int.from_bytes(hashlib.sha256(f"{seed}|{k}|{stream_name}".encode()).digest()[:8], "big"))`
or a PCG substream — never from a single running generator advanced
across the whole passage. A generator that resets or advances differently per chunk would make the
same passage produce different events depending on how catch-up was chunked. `passage/engine/rng.py`
provides `rng_for_step(seed: int, step_index: int, stream: str) -> random.Random`.

**Do NOT key the substream with the builtin `hash()` on strings/tuples.** Python salts string/bytes
hashing per process (`PYTHONHASHSEED`), so `hash((seed, k, stream_name))` yields different values in
different processes and would make replays (Phase 7) and cross-invocation catch-up non-deterministic.
Use a stable digest (as above) or map `stream_name` to a fixed integer. A Phase-1 test should assert
`rng_for_step` returns identical draws in a fresh subprocess.

---

## 8. NEEDS-JUDGMENT tuning (`passage/engine/tuning.py`)

Placeholder values behind named constants. Structure frozen; values tuned in a later spec session
with Steven. Do not tune in an implementation session (CLAUDE.md).

```python
# NEEDS-JUDGMENT — placeholder values, do not tune in an implementation session
UPWIND_LIMIT_DEG: float = 40.0     # closest TWA the boat will point
DOWNWIND_LIMIT_DEG: float = 170.0  # deepest TWA before forcing a gybe angle
LEEWAY_COEFF: float = 0.0          # deg of leeway per unit; 0 disables leeway in Phase 1
TACK_HYSTERESIS_DEG: float = 0.0   # 0 = none; raise only via a spec decision if oscillation appears

def wave_drag_factor(wave_height_m: float) -> float:
    # multiplicative BSP factor in (0,1]. Placeholder: mild linear knockdown, floored.
    # e.g. max(0.6, 1.0 - 0.02 * wave_height_m). Tuned later.
    ...
```

Boat-preset polar numbers (in `boats.py`) are likewise NEEDS-JUDGMENT placeholders.

---

## 9. Settings additions (contract change to `specs/api-skeleton.md` Settings)

Add one field to `Settings` (`passage/config.py`):

| Field | Env var | Default | Meaning |
|---|---|---|---|
| `max_catchup_hours_per_request: int` | `PASSAGE_MAX_CATCHUP_HOURS_PER_REQUEST` | `6` | Per-request catch-up bound; keeps a chunk under the Vercel function timeout. |

Update `.env.example` and `specs/api-skeleton.md`'s Settings table accordingly (a Phase-1 ticket does this).

---

## 10. What is explicitly NOT in Phase 1

Sail-plan performance effects, reef granularity, headsail choice (Pre-3); conditional standing-orders
rules (Pre-3); events/damage/resources/crew/RNG draws (Phase 5); tides & real ocean currents as a
data source (Phase 6 — the *current-set math* is built and tested now with synthetic current, but
Phase-1 real data supplies `current_*` = 0); GRIB planning tools (Phase 4); optimal-routing baseline
& replay UI (Phase 7). High-latitude/polar routing. Leeway (structure only, coeff 0).
