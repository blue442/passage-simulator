# CONTRACT — see specs/engine-state.md §3.
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, Field

from passage.engine.polars import PolarTable

if TYPE_CHECKING:
    # Only for type checkers: importing passage.engine.orders here at runtime would create a
    # real import cycle (orders.py needs GeoPoint from this module). The forward reference
    # below is resolved once, after both modules load, by passage.engine.__init__.
    from passage.engine.orders import Orders


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
    wind_dir_deg: float            # TWD, direction FROM, [0,360)
    gust_kn: float
    pressure_hpa: float
    wave_height_m: float
    current_speed_kn: float = 0.0  # 0 from Phase-1 real data; nonzero in golden fixtures & Phase 6
    current_dir_deg: float = 0.0   # direction flowing TOWARD, [0,360)


class VesselState(BaseModel):
    # The dynamic state that carries between steps. This is the authoritative resume state:
    # the passage row persists exactly this (denormalized) and each catch-up resumes from it.
    time: datetime                 # simulated UTC timestamp; always started_at + k*STEP
    position: GeoPoint
    heading_deg: float              # course steered on the step that produced this state (COG)
    speed_kn: float                 # SOG on that step
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
    CONDITIONS = "conditions"      # hourly conditions summary
    WAYPOINT = "waypoint"
    ARRIVAL = "arrival"
    GROUNDING = "grounding"
    # Phase 5 adds: EVENT, DAMAGE, RESOURCE, etc. Keep additive.


class LogEntry(BaseModel):
    time: datetime
    category: LogCategory
    message: str                   # plain factual text in Phase 1; narrative voice is Pre-5
    data: dict = Field(default_factory=dict)  # structured payload (jsonb in DB)


class BoatPreset(BaseModel):
    key: str
    name: str
    hull_length_m: float
    max_hull_speed_kn: float        # used for the arrival-radius sanity rule
    polar: PolarTable


class PassageParams(BaseModel):
    # Static inputs for a segment. Assembled by the caller from the passage row + boat registry.
    boat: BoatPreset
    orders: Orders                  # from passage.engine.orders (specs/orders.md)
    destination: GeoPoint
    seed: int
    started_at: datetime            # sim-clock origin; step_index = round((t - started_at)/STEP)


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
