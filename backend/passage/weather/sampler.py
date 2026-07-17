# CONTRACT — see specs/weather-cache.md §4; specs/golden-fixtures.md GF-8.
#
# This module builds a PURE closure over already-fetched, in-memory rows -- no I/O happens once
# `build_sampler` returns. This is the seam that keeps passage.engine pure (specs/engine-state.md
# WeatherProvider protocol).
import math
from datetime import datetime, timedelta

from passage.engine.constants import TILE_RESOLUTION_DEG
from passage.engine.state import WeatherSample

_REQUIRED_FIELDS = ("wind_speed_kn", "wind_dir_deg", "gust_kn", "pressure_hpa", "wave_height_m")
_ANGLE_FIELDS = {"wind_dir_deg"}


class MissingWeatherDataError(LookupError):
    """Raised when a query needs a tile/hour/field not present in the loaded rows. This is a
    prefetch bug (box too small or the boat left the box) -- the sampler never extrapolates
    (specs/weather-cache.md §4)."""


def _bilinear(v_lo_lo: float, v_lo_hi: float, v_hi_lo: float, v_hi_hi: float, lat_frac: float, lon_frac: float) -> float:
    v_lat_lo = v_lo_lo * (1 - lon_frac) + v_lo_hi * lon_frac
    v_lat_hi = v_hi_lo * (1 - lon_frac) + v_hi_hi * lon_frac
    return v_lat_lo * (1 - lat_frac) + v_lat_hi * lat_frac


def build_sampler(rows: list[dict]):
    """rows: dicts with keys source, lat_idx, lon_idx, hour_utc, latitude, longitude, variables
    (the shape `cache.read_rows` returns). Returns a pure WeatherProvider closure
    (lat, lon, time) -> WeatherSample."""
    merged: dict[tuple[int, int, datetime], dict[str, float]] = {}
    for row in rows:
        key = (row["lat_idx"], row["lon_idx"], row["hour_utc"])
        merged.setdefault(key, {}).update(row["variables"])

    def _corner(lat_idx: int, lon_idx: int, hour: datetime, field: str) -> float:
        values = merged.get((lat_idx, lon_idx, hour))
        if values is None or field not in values:
            raise MissingWeatherDataError(
                f"no cached {field!r} for lat_idx={lat_idx}, lon_idx={lon_idx}, hour_utc={hour}"
            )
        return values[field]

    def _scalar_field(
        lat_idx_lo: int, lon_idx_lo: int, hour_lo: datetime, hour_hi: datetime,
        lat_frac: float, lon_frac: float, time_frac: float, field: str,
    ) -> float:
        def at_hour(hour: datetime) -> float:
            return _bilinear(
                _corner(lat_idx_lo, lon_idx_lo, hour, field),
                _corner(lat_idx_lo, lon_idx_lo + 1, hour, field),
                _corner(lat_idx_lo + 1, lon_idx_lo, hour, field),
                _corner(lat_idx_lo + 1, lon_idx_lo + 1, hour, field),
                lat_frac, lon_frac,
            )

        v_h0 = at_hour(hour_lo)
        v_h1 = at_hour(hour_hi)
        return v_h0 * (1 - time_frac) + v_h1 * time_frac

    def _angle_field(
        lat_idx_lo: int, lon_idx_lo: int, hour_lo: datetime, hour_hi: datetime,
        lat_frac: float, lon_frac: float, time_frac: float, field: str,
    ) -> float:
        def sin_cos_at_hour(hour: datetime) -> tuple[float, float]:
            degs = (
                _corner(lat_idx_lo, lon_idx_lo, hour, field),
                _corner(lat_idx_lo, lon_idx_lo + 1, hour, field),
                _corner(lat_idx_lo + 1, lon_idx_lo, hour, field),
                _corner(lat_idx_lo + 1, lon_idx_lo + 1, hour, field),
            )
            sins = [math.sin(math.radians(d)) for d in degs]
            coss = [math.cos(math.radians(d)) for d in degs]
            return _bilinear(*sins, lat_frac, lon_frac), _bilinear(*coss, lat_frac, lon_frac)

        sin_h0, cos_h0 = sin_cos_at_hour(hour_lo)
        sin_h1, cos_h1 = sin_cos_at_hour(hour_hi)
        sin_mid = sin_h0 * (1 - time_frac) + sin_h1 * time_frac
        cos_mid = cos_h0 * (1 - time_frac) + cos_h1 * time_frac
        return math.degrees(math.atan2(sin_mid, cos_mid)) % 360.0

    def sampler(lat: float, lon: float, time: datetime) -> WeatherSample:
        lat_pos = (lat + 90.0) / TILE_RESOLUTION_DEG
        lon_pos = (lon + 180.0) / TILE_RESOLUTION_DEG
        lat_idx_lo = math.floor(lat_pos)
        lon_idx_lo = math.floor(lon_pos)
        lat_frac = lat_pos - lat_idx_lo
        lon_frac = lon_pos - lon_idx_lo

        hour_lo = time.replace(minute=0, second=0, microsecond=0)
        hour_hi = hour_lo + timedelta(hours=1)
        time_frac = (time - hour_lo).total_seconds() / 3600.0

        values = {}
        for field in _REQUIRED_FIELDS:
            interp = _angle_field if field in _ANGLE_FIELDS else _scalar_field
            values[field] = interp(lat_idx_lo, lon_idx_lo, hour_lo, hour_hi, lat_frac, lon_frac, time_frac, field)

        return WeatherSample(
            wind_speed_kn=values["wind_speed_kn"],
            wind_dir_deg=values["wind_dir_deg"],
            gust_kn=values["gust_kn"],
            pressure_hpa=values["pressure_hpa"],
            wave_height_m=values["wave_height_m"],
            current_speed_kn=0.0,
            current_dir_deg=0.0,
        )

    return sampler
