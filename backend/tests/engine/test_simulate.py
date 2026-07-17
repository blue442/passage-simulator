from datetime import UTC, datetime

from passage.engine.boats import get_boat
from passage.engine.constants import STEP
from passage.engine.orders import Orders, RoutingMode
from passage.engine.polars import PolarTable
from passage.engine.simulate import simulate_segment
from passage.engine.state import (
    GeoPoint,
    LogCategory,
    PassageParams,
    PassageStatus,
    VesselState,
    WeatherSample,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)

POLAR_TEST = PolarTable(
    tws_values=[6, 10],
    twa_values=[45, 90, 135],
    boat_speed=[[3.0, 5.0], [4.0, 6.5], [3.5, 5.5]],
)


class _AlwaysWater:
    def is_water(self, lat: float, lon: float) -> bool:
        return True


class _LandEastOf05:
    def is_water(self, lat: float, lon: float) -> bool:
        return lon < 0.5


def _boat():
    boat = get_boat("cruiser35")
    return boat.model_copy(update={"polar": POLAR_TEST})


def _constant_weather(ws: WeatherSample):
    def provider(lat: float, lon: float, time: datetime) -> WeatherSample:
        return ws
    return provider


class TestGF5WaypointAdvanceAndArrival:
    def test_advance(self) -> None:
        wp1 = GeoPoint(lat=1.0, lon=0.0)
        wp2 = GeoPoint(lat=2.0, lon=0.0)
        orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[wp1, wp2])
        start = VesselState(
            time=T0, position=GeoPoint(lat=1.0 - 1 / 60, lon=0.0), heading_deg=0.0, speed_kn=0.0
        )
        params = PassageParams(boat=_boat(), orders=orders, destination=wp2, seed=1, started_at=T0)
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013, wave_height_m=0.0)

        result = simulate_segment(params, start, _constant_weather(ws), _AlwaysWater(), until=T0 + STEP)

        assert result.end_state.active_waypoint_index == 1
        assert result.end_state.status == PassageStatus.ACTIVE
        waypoint_entries = [e for e in result.log_entries if e.category == LogCategory.WAYPOINT]
        assert len(waypoint_entries) == 1

    def test_arrival(self) -> None:
        wp1 = GeoPoint(lat=1.0, lon=0.0)
        orders = Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[wp1])
        start = VesselState(
            time=T0, position=GeoPoint(lat=1.0 - 1 / 60, lon=0.0), heading_deg=0.0, speed_kn=0.0
        )
        params = PassageParams(boat=_boat(), orders=orders, destination=wp1, seed=1, started_at=T0)
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013, wave_height_m=0.0)

        # `until` allows 10 steps' worth of time; arrival must stop the loop after just 1.
        result = simulate_segment(params, start, _constant_weather(ws), _AlwaysWater(), until=T0 + 10 * STEP)

        assert result.end_state.status == PassageStatus.ARRIVED
        assert result.end_state.time == T0 + STEP
        arrival_entries = [e for e in result.log_entries if e.category == LogCategory.ARRIVAL]
        assert len(arrival_entries) == 1
        assert len(result.track_points) == 1


class TestGF7Grounding:
    def test_grounding_stops_stepping_at_first_crossing(self) -> None:
        orders = Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=90.0)
        destination = GeoPoint(lat=0.0, lon=100.0)  # far away; never reached before grounding
        start = VesselState(time=T0, position=GeoPoint(lat=0.0, lon=0.0), heading_deg=0.0, speed_kn=0.0)
        params = PassageParams(boat=_boat(), orders=orders, destination=destination, seed=1, started_at=T0)
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=0, gust_kn=12, pressure_hpa=1013, wave_height_m=0.0)

        result = simulate_segment(
            params, start, _constant_weather(ws), _LandEastOf05(), until=T0 + 50 * STEP
        )

        assert result.end_state.status == PassageStatus.GROUNDED
        grounding_entries = [e for e in result.log_entries if e.category == LogCategory.GROUNDING]
        assert len(grounding_entries) == 1
        assert result.track_points[-1].position.lon >= 0.5
        assert all(tp.position.lon < 0.5 for tp in result.track_points[:-1])
        assert result.end_state.position == result.track_points[-1].position
