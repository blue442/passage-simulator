# CONTRACT: Golden Fixtures (Phase 1)

Frozen by the Pre-1 spec session (2026-07-15). These are the "correctness is subtle" tests with
hand-checked expected values. Implementation tickets must make them pass **exactly** (not
approximately, except where a tolerance is stated). Where a value is marked *(compute & freeze)*,
the implementer computes it once, writes it into the test as a literal, and it becomes frozen —
if it later changes, that is an escalation, not an edit.

Shared inputs live in `backend/tests/fixtures/`. The synthetic test polar is `polar_test.json`
(NOT a boat preset):

```
tws_values = [6, 10]
twa_values = [45, 90, 135]
boat_speed[twa_idx][tws_idx]:
        tws=6   tws=10
twa=45   3.0     5.0
twa=90   4.0     6.5
twa=135  3.5     5.5
```

All angles compass degrees, distances nm, speeds kn, times UTC. `STEP = 10 min = 1/6 h`.

---

## GF-1 — Polar bilinear interpolation (`tests/engine/test_polars.py`)

`boat_speed(polar_test, tws, twa)`:

| tws | twa | expected | why |
|---|---|---|---|
| 6 | 45 | **3.0** | grid corner |
| 10 | 135 | **5.5** | grid corner |
| 8 | 90 | **5.25** | linear in tws: 4.0 + 0.5·(6.5−4.0) |
| 8 | 67.5 | **4.625** | bilinear: tws6→3.5, tws10→5.75, mid→4.625 |
| 4 | 90 | **4.0** | tws below range → clamp to 6 |
| 12 | 90 | **6.5** | tws above range → clamp to 10 |
| 8 | −90 | **5.25** | TWA folded by abs → 90 |

Exact equality (these are exact in binary-friendly fractions; allow `abs < 1e-9`).

---

## GF-2 — Great-circle distance & bearing (`tests/geo/test_geo.py`)

`distance_nm` / `initial_bearing_deg`, EARTH_RADIUS_NM = 3440.065:

| a | b | distance_nm | bearing_deg |
|---|---|---|---|
| (0,0) | (1,0) | **60.0** (±1e-6) | **0.0** |
| (0,0) | (0,1) | **60.0** (±1e-3) | **90.0** |
| (0,0) | (−1,0) | **60.0** (±1e-6) | **180.0** |
| (0,0) | (0,−1) | **60.0** (±1e-3) | **270.0** |
| (0,0) | (1,1) | **≈84.851** *(compute & freeze, ±1e-3)* | **≈45.0** *(44.996; compute & freeze, ±1e-2)* |

The meridian/equator rows are exactly `60.0` **only** because `EARTH_RADIUS_NM = 3437.7468`
(= 60·180/π), which is what makes "1° = 60 nm exactly" (§1) hold. If that constant is ever changed
back to a geodetic value (e.g. 3440.065), these rows become ≈60.04 and the diagonal ≈84.91 — the
whole table must be recomputed. Diagonal ≈84.851 is with the frozen 3437.7468.

Antimeridian: `offset((0,179.9), 90, 60)` must land near `lon ≈ −179.1` (wrapped), lat ≈ 0 — assert
`lon` is normalized into `[-180,180)` and no exception. *(compute & freeze exact lon)*

---

## GF-3 — Single step with current set (`tests/engine/test_motion.py`)

Setup: start `(lat=0, lon=0)` at `t0`; WAYPOINT mode, single waypoint due north; `WeatherSample`
= `{wind_speed_kn: 10, wind_dir_deg: 90, gust: 12, pressure: 1013, wave_height_m: 0,
current_speed_kn: 3, current_dir_deg: 90}`; polar = `polar_test`; wave_drag disabled (wave_height 0
⇒ factor 1.0); leeway 0.

Reasoning: desired bearing 000; wind from 090 ⇒ TWA for heading 000 is 90 (beam reach), inside
`[UPWIND_LIMIT, DOWNWIND_LIMIT]` ⇒ heading = 000. `boat_speed(10, 90) = 6.5` kn through water.
Current 3 kn toward 090 (east). Vector sum: `vN = 6.5, vE = 3.0`.

Expected after one step:
- `speed_kn (SOG) = hypot(6.5, 3.0) =` **7.1589105** (±1e-6)
- `heading_deg (COG) = degrees(atan2(3.0, 6.5)) =` **24.7751406** (±1e-4)
- `dN_nm = 6.5/6 = 1.0833333`, `dE_nm = 3.0/6 = 0.5`
- `position.lat = 1.0833333/60 =` **0.01805556** (±1e-7)
- `position.lon = 0.5/(60·cos(0)) =` **0.00833333** (±1e-7)
- `distance_run_nm = 7.1589105/6 =` **1.1931518** (±1e-6)
- `time = t0 + STEP`

---

## GF-4 — Single step, no current (`tests/engine/test_motion.py`)

As GF-3 but `current_speed_kn = 0`:
- `speed_kn = 6.5`, `heading_deg = 0.0`
- `position.lat =` **0.01805556**, `position.lon =` **0.0**
- `distance_run_nm = 6.5/6 =` **1.0833333**

---

## GF-5 — Waypoint advance & arrival (`tests/engine/test_simulate.py`)

- **Advance:** `waypoints = [WP1, WP2]`, start 1.0 nm due south of WP1 (inside the 2.0 nm arrival
  radius after the first step). After `simulate_segment` of one step: `active_waypoint_index == 1`,
  exactly one `waypoint` log entry, `status == ACTIVE`.
- **Arrival:** `waypoints = [WP1]` (last), start 1.0 nm south of WP1. After one step:
  `status == ARRIVED`, one `arrival` log entry, stepping stops (no track points past arrival time).

---

## GF-6 — Determinism / chunk invariance (SACRED — `tests/engine/test_determinism.py`)

Use a **pure analytic** `WeatherProvider` (a closure `f(lat, lon, time) -> WeatherSample`, e.g.
constant wind 15 kn from 270, 1 m waves, no current — no cache, no network) so this isolates the
stepping core. Fixed start, `polar_test`, a destination far enough that the boat sails the whole
window without arriving.

Simulate 24 h three ways and assert **bit-identical** results (exact `==` on every TrackPoint field
and on `end_state`):
1. one segment `[t0, t0+24h]`
2. four segments `[t0,+6h], [+6h,+12h], [+12h,+18h], [+18h,+24h]` (feed each segment's `end_state`
   as the next `start_state`)
3. 144 single-step segments

All three track lists must be equal element-by-element. **If this fails, stop and escalate
(trigger 1). Never weaken `==` to `approx`.** This is the tripwire that protects every future phase.

---

## GF-7 — Grounding (`tests/engine/test_simulate.py`)

Stub `land.is_water(lat, lon) = (lon < 0.5)` (land at/after 0.5°E). Start `(0,0)`, HEADING mode
`fixed_heading_deg = 90` (due east), analytic weather giving forward motion, no current. Assert:
`status == GROUNDED`; exactly one `grounding` log entry; stepping stops at the first step whose end
position has `lon >= 0.5`; no track points after the grounding step.

---

## GF-8 — Weather sampler trilinear interpolation (`tests/weather/test_sampler.py`)

Build a sampler over synthetic in-memory rows (no DB). Tiles at (lat_idx→0.0°, 0.25°) ×
(lon_idx→0.0°, 0.25°), two hours H0 and H1 = H0+1h.

`wind_speed_kn` per corner:

| | lon=0.0 | lon=0.25 |
|---|---|---|
| lat=0.0 | H0=10, H1=20 | H0=12, H1=22 |
| lat=0.25 | H0=14, H1=24 | H0=16, H1=26 |

Query `(lat=0.125, lon=0.125, time=H0+30min)` (spatial centre, temporal midpoint):
- bilinear @H0 = 13.0, bilinear @H1 = 23.0, time-linear midpoint = **18.0** (±1e-9).

**Angle wrap:** `wind_dir_deg` two-hour case at a single tile: H0 = 350°, H1 = 10°, query at the
midpoint. Interpolating as unit vectors (sin/cos → atan2) must give **0.0°/360.0°** (±1e-6), NOT
180°. This asserts the frozen "interpolate angles as vectors" rule.

Missing-tile case: querying outside the loaded box must **raise**, not extrapolate.

---

## Notes for implementers

- GF-3/GF-4 use `cos(radians(start-of-step lat))` for the lon divisor (frozen in
  `specs/engine-state.md` §6). At lat 0 this is 1.0.
- Do not "fix" a failing GF-6/GF-2 by adjusting tolerances or reordering float operations without a
  spec consult — operation order is frozen precisely because it changes the last bits.
- The *(compute & freeze)* values (GF-2 diagonal, antimeridian lon) are computed once by the
  implementer and committed as literals; note them in the ticket when done.
