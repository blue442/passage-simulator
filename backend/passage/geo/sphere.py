# CONTRACT — see specs/engine-state.md §5; specs/golden-fixtures.md GF-2.
import math

from passage.engine.constants import EARTH_RADIUS_NM
from passage.engine.state import GeoPoint

# High latitude (|lat| > 85 deg) or a great-circle path that crosses within this limit of a
# pole: escalate (trigger 3, specs/engine-state.md §5). Phase-1 passages are temperate/
# tropical; polar routing is out of scope.
HIGH_LATITUDE_LIMIT_DEG: float = 85.0


class HighLatitudeError(ValueError):
    """Raised when a geo computation involves a point, or a great-circle path, within
    HIGH_LATITUDE_LIMIT_DEG of a pole. Phase-1 polar routing is out of scope — this is an
    escalation marker (trigger 3), not a value to silently clamp or extrapolate past."""


def normalize_lon(lon_deg: float) -> float:
    """Normalize a longitude to [-180, 180) (antimeridian safe)."""
    return ((lon_deg + 180.0) % 360.0) - 180.0


def _check_point_lat(lat_deg: float) -> None:
    if abs(lat_deg) > HIGH_LATITUDE_LIMIT_DEG:
        raise HighLatitudeError(
            f"|lat|={abs(lat_deg)!r} exceeds {HIGH_LATITUDE_LIMIT_DEG} deg; "
            "polar routing is out of Phase-1 scope"
        )


def distance_nm(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance in nm (haversine)."""
    _check_point_lat(a.lat)
    _check_point_lat(b.lat)
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(h))


def initial_bearing_deg(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle initial bearing a -> b, in [0, 360)."""
    _check_point_lat(a.lat)
    _check_point_lat(b.lat)
    lat1, lon1 = math.radians(a.lat), math.radians(a.lon)
    lat2, lon2 = math.radians(b.lat), math.radians(b.lon)
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(y, x)) % 360.0


def _max_abs_lat_deg_along_path(lat1_deg: float, bearing_deg: float, dist_nm: float, lat2_deg: float) -> float:
    """Max |latitude| (deg) reached anywhere along a great-circle arc of length dist_nm from
    lat1_deg on initial bearing bearing_deg, using Clairaut's relation for the great circle's
    vertex (turning point). The destination-point formula in `offset` is globally valid even
    when the path sweeps past a pole, so the two endpoint latitudes alone are not sufficient
    evidence of what happened in between (a path can cross deep into polar latitudes and still
    land back at an innocuous-looking endpoint). This checks whether a vertex lies within the
    traveled arc and, if so, returns its latitude instead of just the endpoints'.
    """
    lat1 = math.radians(lat1_deg)
    brg = math.radians(bearing_deg)
    dr = dist_nm / EARTH_RADIUS_NM

    clairaut_c = min(1.0, abs(math.cos(lat1) * math.sin(brg)))
    vertex_lat_deg = math.degrees(math.acos(clairaut_c))

    # sigma parameterizes angular position along the track; vertices (max |lat|, direction
    # reversal in latitude) occur where sigma = pi/2 + k*pi for integer k.
    sigma1 = math.atan2(math.tan(lat1), math.cos(brg))
    sigma2 = sigma1 + dr
    lo, hi = min(sigma1, sigma2), max(sigma1, sigma2)

    k = math.floor((lo - math.pi / 2) / math.pi)
    while True:
        vertex_sigma = math.pi / 2 + k * math.pi
        if vertex_sigma > hi + 1e-9:
            return max(abs(lat1_deg), abs(lat2_deg))
        if vertex_sigma >= lo - 1e-9:
            return vertex_lat_deg
        k += 1


def offset(point: GeoPoint, bearing_deg: float, distance_nm: float) -> GeoPoint:
    """Destination point given a start point, initial bearing, and great-circle distance."""
    _check_point_lat(point.lat)
    lat1 = math.radians(point.lat)
    lon1 = math.radians(point.lon)
    brg = math.radians(bearing_deg)
    dr = distance_nm / EARTH_RADIUS_NM

    lat2 = math.asin(math.sin(lat1) * math.cos(dr) + math.cos(lat1) * math.sin(dr) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(dr) * math.cos(lat1),
        math.cos(dr) - math.sin(lat1) * math.sin(lat2),
    )
    lat2_deg = math.degrees(lat2)
    lon2_deg = normalize_lon(math.degrees(lon2))

    max_lat = _max_abs_lat_deg_along_path(point.lat, bearing_deg, distance_nm, lat2_deg)
    if max_lat > HIGH_LATITUDE_LIMIT_DEG:
        raise HighLatitudeError(
            f"great-circle path reaches |lat|={max_lat!r} deg, exceeding "
            f"{HIGH_LATITUDE_LIMIT_DEG} deg; polar routing is out of Phase-1 scope"
        )

    return GeoPoint(lat=lat2_deg, lon=lon2_deg)
