# CONTRACT — see specs/engine-state.md §2. Frozen: changing any of these changes cache keys
# and/or step sequences and breaks determinism / invalidates existing passages. Do not tune.
from datetime import timedelta

STEP: timedelta = timedelta(minutes=10)         # integration step; also the track-point cadence
TILE_RESOLUTION_DEG: float = 0.25               # weather tile snapping grid (specs/weather-cache.md)
NM_PER_DEGREE_LAT: float = 60.0
# = 60*180/pi, so 1 degree = 60 nm exactly (matches NM_PER_DEGREE_LAT); haversine dist/bearing
EARTH_RADIUS_NM: float = 3437.7468
CONDITIONS_LOG_EVERY_STEPS: int = 6             # one "conditions" log entry per hour (6 x 10 min)
