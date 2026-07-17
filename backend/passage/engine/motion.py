# CONTRACT — see specs/engine-state.md §6; specs/golden-fixtures.md GF-3, GF-4.
#
# Order of operations is frozen: desired bearing -> steering clamp (no-go zones) -> boat speed
# -> local-tangent-plane vector sum with current -> displacement -> new state. It affects
# floating-point results and therefore determinism; do not reorder.
import math

from passage.engine import tuning
from passage.engine.constants import NM_PER_DEGREE_LAT, STEP
from passage.engine.orders import Orders, RoutingMode
from passage.engine.polars import boat_speed
from passage.engine.state import BoatPreset, GeoPoint, VesselState, WeatherSample
from passage.geo import initial_bearing_deg, normalize_lon


def _angular_diff(a: float, b: float) -> float:
    """Signed difference a-b folded into (-180, 180]. Positive means a is `diff` degrees
    clockwise from b."""
    return ((a - b + 180.0) % 360.0) - 180.0


def _reciprocal(bearing_deg: float) -> float:
    return (bearing_deg + 180.0) % 360.0


def _desired_bearing(state: VesselState, orders: Orders, destination: GeoPoint) -> float:
    if orders.routing_mode == RoutingMode.HEADING:
        return orders.fixed_heading_deg
    target = orders.waypoints[state.active_waypoint_index] if orders.waypoints else destination
    return initial_bearing_deg(state.position, target)


def _steer(desired_deg: float, wind_from_deg: float) -> float:
    """Clamp `desired_deg` out of the no-go zones (specs/engine-state.md §6 step 2). Starboard
    tack is always `wind_from - TWA` (mod 360) — see the Pre-1 gate review note in the spec for
    the derivation (the wind source sits to the right/starboard of that heading)."""
    twa_desired = abs(_angular_diff(desired_deg, wind_from_deg))

    if tuning.UPWIND_LIMIT_DEG <= twa_desired <= tuning.DOWNWIND_LIMIT_DEG:
        return desired_deg

    if twa_desired < tuning.UPWIND_LIMIT_DEG:
        starboard = (wind_from_deg - tuning.UPWIND_LIMIT_DEG) % 360.0
        port = (wind_from_deg + tuning.UPWIND_LIMIT_DEG) % 360.0
    else:
        delta = 180.0 - tuning.DOWNWIND_LIMIT_DEG
        recip = _reciprocal(wind_from_deg)
        starboard = (recip + delta) % 360.0
        port = (recip - delta) % 360.0

    dist_starboard = abs(_angular_diff(starboard, desired_deg))
    dist_port = abs(_angular_diff(port, desired_deg))
    if dist_port < dist_starboard:
        return port
    return starboard  # closer, or an exact tie: frozen tie-break favors starboard


def step(
    state: VesselState,
    ws: WeatherSample,
    orders: Orders,
    destination: GeoPoint,
    boat: BoatPreset,
) -> VesselState:
    """Advance the vessel by exactly STEP. Pure."""
    desired = _desired_bearing(state, orders, destination)
    heading = _steer(desired, ws.wind_dir_deg)

    twa_realized = abs(_angular_diff(heading, ws.wind_dir_deg))
    bsp = boat_speed(boat.polar, ws.wind_speed_kn, twa_realized)
    bsp *= tuning.wave_drag_factor(ws.wave_height_m)

    heading_rad = math.radians(heading)
    v_n_boat = bsp * math.cos(heading_rad)
    v_e_boat = bsp * math.sin(heading_rad)

    current_dir_rad = math.radians(ws.current_dir_deg)
    v_n_current = ws.current_speed_kn * math.cos(current_dir_rad)
    v_e_current = ws.current_speed_kn * math.sin(current_dir_rad)

    v_n = v_n_boat + v_n_current
    v_e = v_e_boat + v_e_current
    sog = math.hypot(v_n, v_e)
    cog = math.degrees(math.atan2(v_e, v_n)) % 360.0

    dt_hours = STEP.total_seconds() / 3600.0
    d_n_nm = v_n * dt_hours
    d_e_nm = v_e * dt_hours

    start_lat = state.position.lat
    new_lat = start_lat + d_n_nm / NM_PER_DEGREE_LAT
    new_lon = normalize_lon(
        state.position.lon + d_e_nm / (NM_PER_DEGREE_LAT * math.cos(math.radians(start_lat)))
    )

    return VesselState(
        time=state.time + STEP,
        position=GeoPoint(lat=new_lat, lon=new_lon),
        heading_deg=cog,
        speed_kn=sog,
        active_waypoint_index=state.active_waypoint_index,
        distance_run_nm=state.distance_run_nm + sog * dt_hours,
        status=state.status,
    )
