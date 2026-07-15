# CONTRACT — see specs/orders.md.
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from passage.engine.state import GeoPoint


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
    arrival_radius_nm: float = 2.0            # NEEDS-JUDGMENT default; see constraint below

    @model_validator(mode="after")
    def _validate_semantics(self) -> "Orders":
        if self.routing_mode == RoutingMode.HEADING:
            if self.fixed_heading_deg is None:
                raise ValueError("fixed_heading_deg is required when routing_mode is HEADING")
            if not (0 <= self.fixed_heading_deg < 360):
                raise ValueError("fixed_heading_deg must be in [0, 360)")
        if self.arrival_radius_nm < 1.6:
            # arrival is only checked at step boundaries; a radius below the max per-step
            # displacement (max_hull_speed_kn * STEP, ~1.5 nm) lets the boat step across the
            # circle without ever being detected inside it (specs/orders.md).
            raise ValueError("arrival_radius_nm must be >= 1.6")
        return self
