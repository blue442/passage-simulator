# CONTRACT — see specs/engine-state.md §7; specs/golden-fixtures.md GF-5, GF-6, GF-7.
from datetime import datetime, timedelta

from passage.engine.constants import CONDITIONS_LOG_EVERY_STEPS, STEP
from passage.engine.motion import step as motion_step
from passage.engine.orders import RoutingMode
from passage.engine.state import (
    GeoPoint,
    LandQuery,
    LogCategory,
    LogEntry,
    PassageParams,
    PassageStatus,
    SegmentResult,
    TrackPoint,
    VesselState,
    WeatherProvider,
    WeatherSample,
)
from passage.geo import distance_nm


def _active_target(params: PassageParams, active_waypoint_index: int) -> GeoPoint:
    # HEADING mode ignores waypoints entirely (specs/orders.md): arrival is only ever checked
    # against the passage destination, regardless of what orders.waypoints happens to contain.
    if params.orders.routing_mode == RoutingMode.HEADING:
        return params.destination
    waypoints = params.orders.waypoints
    if waypoints:
        return waypoints[active_waypoint_index]
    return params.destination


def _is_terminal_target(params: PassageParams, active_waypoint_index: int) -> bool:
    if params.orders.routing_mode == RoutingMode.HEADING:
        return True
    waypoints = params.orders.waypoints
    if not waypoints:
        return True
    return active_waypoint_index >= len(waypoints) - 1


def _track_point(state: VesselState, ws: WeatherSample) -> TrackPoint:
    return TrackPoint(
        time=state.time,
        position=state.position,
        heading_deg=state.heading_deg,
        speed_kn=state.speed_kn,
        tws_kn=ws.wind_speed_kn,
        twd_deg=ws.wind_dir_deg,
        gust_kn=ws.gust_kn,
        pressure_hpa=ws.pressure_hpa,
        wave_height_m=ws.wave_height_m,
    )


def simulate_segment(
    params: PassageParams,
    start_state: VesselState,
    weather: WeatherProvider,
    land: LandQuery,
    until: datetime,
) -> SegmentResult:
    k0 = round((start_state.time - params.started_at) / STEP)
    assert start_state.time == params.started_at + k0 * STEP, "start_state.time must be step-aligned"
    assert (until - params.started_at) % STEP == timedelta(0), "until must be step-aligned"

    state = start_state
    track_points: list[TrackPoint] = []
    log_entries: list[LogEntry] = []
    steps_done = 0

    # Distance since the last "conditions" log, local to THIS call. It is NOT chunk-invariant
    # across a catch-up that splits an hour across two requests (common in practice, since
    # check-ins land at arbitrary real-world times): the first conditions entry after such a
    # split under-reports the hour's true distance, because this function has no visibility
    # into steps simulated by an earlier call. This only affects the narrative log's `data`
    # payload, never TrackPoint/VesselState (GF-6 does not check log_entries content, and this
    # value has no bearing on the sacred track/end_state determinism). Flagged in tickets/phase-1.md.
    distance_since_last_conditions_log = 0.0

    while state.time < until and state.status == PassageStatus.ACTIVE:
        ws = weather(state.position.lat, state.position.lon, state.time)
        next_state = motion_step(state, ws, params.orders, params.destination, params.boat)
        steps_done += 1
        k = k0 + steps_done
        distance_since_last_conditions_log += next_state.distance_run_nm - state.distance_run_nm

        if not land.is_water(next_state.position.lat, next_state.position.lon):
            next_state = next_state.model_copy(update={"status": PassageStatus.GROUNDED})
            track_points.append(_track_point(next_state, ws))
            log_entries.append(
                LogEntry(
                    time=next_state.time,
                    category=LogCategory.GROUNDING,
                    message=f"Ran aground near {next_state.position.lat:.4f}, {next_state.position.lon:.4f}.",
                    data={"lat": next_state.position.lat, "lon": next_state.position.lon},
                )
            )
            state = next_state
            break

        target = _active_target(params, next_state.active_waypoint_index)
        if distance_nm(next_state.position, target) <= params.orders.arrival_radius_nm:
            if _is_terminal_target(params, next_state.active_waypoint_index):
                next_state = next_state.model_copy(update={"status": PassageStatus.ARRIVED})
                track_points.append(_track_point(next_state, ws))
                log_entries.append(
                    LogEntry(
                        time=next_state.time,
                        category=LogCategory.ARRIVAL,
                        message="Arrived at destination.",
                        data={"distance_run_nm": next_state.distance_run_nm},
                    )
                )
                state = next_state
                break

            reached_index = next_state.active_waypoint_index
            next_state = next_state.model_copy(update={"active_waypoint_index": reached_index + 1})
            log_entries.append(
                LogEntry(
                    time=next_state.time,
                    category=LogCategory.WAYPOINT,
                    message=f"Reached waypoint {reached_index}.",
                    data={"waypoint_index": reached_index},
                )
            )

        track_points.append(_track_point(next_state, ws))

        if k % CONDITIONS_LOG_EVERY_STEPS == 0:
            log_entries.append(
                LogEntry(
                    time=next_state.time,
                    category=LogCategory.CONDITIONS,
                    message=(
                        f"Position {next_state.position.lat:.4f}, {next_state.position.lon:.4f}; "
                        f"TWS {ws.wind_speed_kn:.1f}kn from {ws.wind_dir_deg:.0f}; "
                        f"waves {ws.wave_height_m:.1f}m; "
                        f"{distance_since_last_conditions_log:.1f}nm run this hour."
                    ),
                    data={
                        "lat": next_state.position.lat,
                        "lon": next_state.position.lon,
                        "tws_kn": ws.wind_speed_kn,
                        "twd_deg": ws.wind_dir_deg,
                        "wave_height_m": ws.wave_height_m,
                        "distance_run_nm": distance_since_last_conditions_log,
                    },
                )
            )
            distance_since_last_conditions_log = 0.0

        state = next_state

    return SegmentResult(end_state=state, track_points=track_points, log_entries=log_entries)
