import math
from datetime import UTC, datetime

import pytest

from passage.engine.boats import get_boat
from passage.engine.constants import STEP
from passage.engine.motion import _steer, step
from passage.engine.orders import Orders, RoutingMode
from passage.engine.polars import PolarTable
from passage.engine.state import GeoPoint, VesselState, WeatherSample

T0 = datetime(2026, 1, 1, tzinfo=UTC)

POLAR_TEST = PolarTable(
    tws_values=[6, 10],
    twa_values=[45, 90, 135],
    boat_speed=[[3.0, 5.0], [4.0, 6.5], [3.5, 5.5]],
)


def _boat():
    boat = get_boat("cruiser35")
    return boat.model_copy(update={"polar": POLAR_TEST})


def _state(lat: float = 0.0, lon: float = 0.0, heading: float = 0.0, speed: float = 0.0) -> VesselState:
    return VesselState(time=T0, position=GeoPoint(lat=lat, lon=lon), heading_deg=heading, speed_kn=speed)


def _calm_ws(wind_dir_deg: float, current_speed_kn: float = 0.0, current_dir_deg: float = 0.0) -> WeatherSample:
    return WeatherSample(
        wind_speed_kn=10, wind_dir_deg=wind_dir_deg, gust_kn=12, pressure_hpa=1013,
        wave_height_m=0.0, current_speed_kn=current_speed_kn, current_dir_deg=current_dir_deg,
    )


class TestGF3WithCurrent:
    def test_single_step_with_current(self) -> None:
        state = _state()
        ws = _calm_ws(wind_dir_deg=90, current_speed_kn=3, current_dir_deg=90)
        orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[GeoPoint(lat=10.0, lon=0.0)])
        new_state = step(state, ws, orders, destination=GeoPoint(lat=10.0, lon=0.0), boat=_boat())

        assert new_state.speed_kn == pytest.approx(7.1589105, abs=1e-6)
        assert new_state.heading_deg == pytest.approx(24.7751406, abs=1e-4)
        assert new_state.position.lat == pytest.approx(0.01805556, abs=1e-7)
        assert new_state.position.lon == pytest.approx(0.00833333, abs=1e-7)
        assert new_state.distance_run_nm == pytest.approx(1.1931518, abs=1e-6)
        assert new_state.time == T0 + STEP


class TestGF4NoCurrent:
    def test_single_step_no_current(self) -> None:
        state = _state()
        ws = _calm_ws(wind_dir_deg=90)
        orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[GeoPoint(lat=10.0, lon=0.0)])
        new_state = step(state, ws, orders, destination=GeoPoint(lat=10.0, lon=0.0), boat=_boat())

        assert new_state.speed_kn == pytest.approx(6.5, abs=1e-9)
        assert new_state.heading_deg == pytest.approx(0.0, abs=1e-9)
        assert new_state.position.lat == pytest.approx(0.01805556, abs=1e-7)
        assert new_state.position.lon == pytest.approx(0.0, abs=1e-9)
        assert new_state.distance_run_nm == pytest.approx(1.0833333, abs=1e-6)


class TestSteeringNoGoZones:
    # Hand-checked with wind_from=0 (from due north), UPWIND_LIMIT_DEG=40, DOWNWIND_LIMIT_DEG=170
    # (tuning.py placeholders). The tie-break cases exercise exactly the bug the Pre-1 gate review
    # found and fixed: the old (backwards) wording would have picked the opposite heading here.
    def test_beam_reach_is_unclamped(self) -> None:
        assert _steer(desired_deg=0.0, wind_from_deg=270.0) == pytest.approx(0.0, abs=1e-9)

    def test_dead_upwind_tie_picks_starboard(self) -> None:
        # desired == wind_from == 0 (dead upwind): candidates wind_from-40=320 (starboard) and
        # wind_from+40=40 (port) are exactly equidistant from desired -> tie -> starboard (320).
        heading = _steer(desired_deg=0.0, wind_from_deg=0.0)
        assert heading == pytest.approx(320.0, abs=1e-9)
        # Positive VMG toward the (dead upwind) mark: bearing 320 is 40 deg off desired 0.
        assert math.cos(math.radians(40.0)) > 0

    def test_dead_downwind_tie_picks_starboard(self) -> None:
        # desired == reciprocal(wind_from) == 180 (dead downwind): candidates
        # reciprocal+10=190 (starboard) and reciprocal-10=170 (port) are tied -> starboard (190).
        heading = _steer(desired_deg=180.0, wind_from_deg=0.0)
        assert heading == pytest.approx(190.0, abs=1e-9)

    def test_pinching_favors_closer_tack_not_always_starboard(self) -> None:
        # desired=20 is closer to the port candidate (40) than the starboard one (320) -- confirms
        # the tie-break rule only fires on an exact tie, not as a blanket "always starboard" rule.
        heading = _steer(desired_deg=20.0, wind_from_deg=0.0)
        assert heading == pytest.approx(40.0, abs=1e-9)

    def test_deep_downwind_favors_closer_tack(self) -> None:
        # desired=175 (TWA=175, past DOWNWIND_LIMIT_DEG=170) is closer to the port candidate
        # (170) than the starboard one (190).
        heading = _steer(desired_deg=175.0, wind_from_deg=0.0)
        assert heading == pytest.approx(170.0, abs=1e-9)


class TestHeadingMode:
    def test_holds_fixed_heading_ignoring_waypoints(self) -> None:
        state = _state()
        ws = _calm_ws(wind_dir_deg=0.0)  # wind from N; heading 90 (E) is a beam reach, unclamped
        orders = Orders(
            routing_mode=RoutingMode.HEADING, fixed_heading_deg=90.0,
            waypoints=[GeoPoint(lat=10.0, lon=0.0)],  # due north -- would desire 0 if honored
        )
        new_state = step(state, ws, orders, destination=GeoPoint(lat=0.0, lon=-10.0), boat=_boat())
        assert new_state.heading_deg == pytest.approx(90.0, abs=1e-9)


class TestWaveDrag:
    def test_wave_height_reduces_boat_speed(self) -> None:
        calm = _calm_ws(wind_dir_deg=90)
        rough = calm.model_copy(update={"wave_height_m": 5.0})
        orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[GeoPoint(lat=10.0, lon=0.0)])
        boat = _boat()
        state = _state()

        calm_state = step(state, calm, orders, destination=GeoPoint(lat=10.0, lon=0.0), boat=boat)
        rough_state = step(state, rough, orders, destination=GeoPoint(lat=10.0, lon=0.0), boat=boat)
        assert rough_state.speed_kn < calm_state.speed_kn
