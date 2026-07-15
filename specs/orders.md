# CONTRACT: Orders (v0)

Frozen by the Pre-1 spec session (2026-07-15). Orders are the skipper's standing instructions to
the boat: where to go and what sails to carry. Phase 1 freezes **v0**: waypoints/course plus a
minimal sail plan. The full conditional-rules DSL (`if TWS > 25 for 30 min, reef`) is the Pre-3
gate and is explicitly out of scope here — do not add conditions, triggers, or time windows.

Orders are a versioned JSON document. They are stored as `jsonb` on the `passage` row (see the
Phase-1 migration) and passed into the pure engine as a Pydantic `Orders` model. They can change
between check-ins (the skipper issues new orders); within a single catch-up segment they are constant.

## Pydantic model (`passage/engine/orders.py`)

```python
# CONTRACT
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field
from passage.engine.state import GeoPoint   # {lat: float, lon: float}


class RoutingMode(str, Enum):
    WAYPOINT = "waypoint"   # steer toward the active waypoint; advance on arrival
    HEADING = "heading"     # hold a fixed compass heading, ignore waypoints


class SailPlan(str, Enum):
    # v0 sail states. Phase 1 records the choice but applies NO performance effect
    # (polars are the same regardless). Phase 3 attaches polar modifiers and wrong-sail
    # penalties to these states and will EXTEND this enum (add headsail choices, storm sails).
    # Keep values additive so Phase 3 does not rewrite stored orders.
    FULL = "full"                 # full main + working headsail
    REEFED = "reefed"             # one reef equivalent
    DEEP_REEFED = "deep_reefed"   # deep reef / small headsail
    STORM = "storm"               # storm canvas


class Orders(BaseModel):
    version: Literal["v0"] = "v0"
    routing_mode: RoutingMode = RoutingMode.WAYPOINT
    waypoints: list[GeoPoint] = Field(default_factory=list)  # ordered; boat heads to waypoints[active_index]
    fixed_heading_deg: float | None = None   # required iff routing_mode == HEADING; 0..360
    sail_plan: SailPlan = SailPlan.FULL
    arrival_radius_nm: float = 2.0           # NEEDS-JUDGMENT default; see constraint below
```

## Semantics (frozen)

- **WAYPOINT mode.** The boat steers toward `waypoints[active_waypoint_index]` (index lives in
  `VesselState`, not here). When the great-circle distance to that waypoint is `<= arrival_radius_nm`
  at a step boundary, the waypoint is "reached": a `waypoint` log entry is emitted and
  `active_waypoint_index` advances. When the **last** waypoint is reached, the passage is `arrived`
  (terminal). The passage `destination` (on the passage row) should normally equal the last waypoint;
  if `waypoints` is empty, the boat steers toward `destination` directly and arrival there is terminal.
- **HEADING mode.** The boat holds `fixed_heading_deg` regardless of waypoints. Used for testing and
  for "run off" style manual control. Arrival is only ever at `destination` (within `arrival_radius_nm`).
- **arrival_radius_nm constraint (frozen).** Arrival is detected only at step boundaries, so the
  radius MUST exceed the maximum distance the boat can travel in one step (`max_hull_speed_kn * STEP`,
  ≈ 1.5 nm at 9 kn over 10 min) or the boat can step across the circle without ever being inside it.
  Default 2.0 nm satisfies this. Validation SHOULD reject `arrival_radius_nm < 1.6`.
- **Upwind / downwind steering (frozen, minimal).** The desired bearing is the great-circle initial
  bearing to the active waypoint (or `fixed_heading_deg` in HEADING mode). The realized heading is
  clamped out of the no-go zones by the motion layer (see `specs/engine-state.md` → "Steering"),
  not here. Orders carry intent; the engine resolves feasibility.
- **Sail plan is inert in Phase 1.** `sail_plan` is stored and echoed but does not change boat speed.
  Do not implement modifiers now — that is Pre-3.

## Validation (frozen)

- `routing_mode == HEADING` ⇒ `fixed_heading_deg` is not None and in `[0, 360)`.
- `routing_mode == WAYPOINT` ⇒ `waypoints` non-empty OR the passage has a `destination` (the engine
  falls back to `destination` when `waypoints` is empty).
- Each waypoint and `fixed_heading_deg` validated as normal `GeoPoint` / angle.
- `arrival_radius_nm >= 1.6`.

## Not in v0 (deferred, do not add)

Conditional rules, triggers, hysteresis, `FOR <duration>` windows, tactic actions (heave-to, run
off, lie ahull), reef-point granularity, headsail selection, per-sail polar modifiers. All Pre-3+.
