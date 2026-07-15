from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from passage.engine import tuning  # noqa: F401 -- exercises the model_rebuild wiring on import
from passage.engine.orders import Orders, RoutingMode, SailPlan
from passage.engine.polars import PolarTable
from passage.engine.state import (
    BoatPreset,
    GeoPoint,
    LogCategory,
    LogEntry,
    PassageParams,
    PassageStatus,
    SegmentResult,
    TrackPoint,
    VesselState,
    WeatherSample,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _polar() -> PolarTable:
    return PolarTable(
        tws_values=[6, 10],
        twa_values=[45, 90, 135],
        boat_speed=[[3.0, 5.0], [4.0, 6.5], [3.5, 5.5]],
    )


def _boat() -> BoatPreset:
    return BoatPreset(key="test", name="Test Boat", hull_length_m=10.0, max_hull_speed_kn=9.0, polar=_polar())


def _orders(**overrides: object) -> Orders:
    return Orders(waypoints=[GeoPoint(lat=1.0, lon=1.0)], **overrides)


class TestGeoPoint:
    def test_round_trip(self) -> None:
        p = GeoPoint(lat=45.5, lon=-122.5)
        assert GeoPoint.model_validate(p.model_dump()) == p

    @pytest.mark.parametrize(
        "lat,lon",
        [(91.0, 0.0), (-91.0, 0.0), (0.0, 180.0), (0.0, -181.0)],
    )
    def test_out_of_range_rejected(self, lat: float, lon: float) -> None:
        with pytest.raises(ValidationError):
            GeoPoint(lat=lat, lon=lon)


class TestWeatherSample:
    def test_defaults_zero_current(self) -> None:
        ws = WeatherSample(wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013, wave_height_m=1.0)
        assert ws.current_speed_kn == 0.0
        assert ws.current_dir_deg == 0.0

    def test_round_trip(self) -> None:
        ws = WeatherSample(
            wind_speed_kn=10, wind_dir_deg=90, gust_kn=12, pressure_hpa=1013,
            wave_height_m=1.0, current_speed_kn=2.0, current_dir_deg=45.0,
        )
        assert WeatherSample.model_validate(ws.model_dump()) == ws


class TestVesselStateAndTrackPoint:
    def test_vessel_state_defaults(self) -> None:
        vs = VesselState(time=T0, position=GeoPoint(lat=0, lon=0), heading_deg=0.0, speed_kn=6.5)
        assert vs.active_waypoint_index == 0
        assert vs.distance_run_nm == 0.0
        assert vs.status == PassageStatus.ACTIVE

    def test_vessel_state_round_trip(self) -> None:
        vs = VesselState(
            time=T0, position=GeoPoint(lat=1, lon=1), heading_deg=45.0, speed_kn=7.0,
            active_waypoint_index=2, distance_run_nm=120.5, status=PassageStatus.GROUNDED,
        )
        assert VesselState.model_validate(vs.model_dump()) == vs

    def test_track_point_round_trip(self) -> None:
        tp = TrackPoint(
            time=T0, position=GeoPoint(lat=0, lon=0), heading_deg=0.0, speed_kn=6.5,
            tws_kn=10.0, twd_deg=90.0, gust_kn=12.0, pressure_hpa=1013.0, wave_height_m=0.0,
        )
        assert TrackPoint.model_validate(tp.model_dump()) == tp


class TestLogEntry:
    def test_default_data_is_empty_dict(self) -> None:
        entry = LogEntry(time=T0, category=LogCategory.DEPARTURE, message="Departed.")
        assert entry.data == {}

    def test_structured_data_round_trip(self) -> None:
        entry = LogEntry(
            time=T0, category=LogCategory.CONDITIONS, message="Winds 15kt.",
            data={"tws_kn": 15.0, "twd_deg": 270.0},
        )
        assert LogEntry.model_validate(entry.model_dump()) == entry

    def test_independent_default_data_dicts(self) -> None:
        a = LogEntry(time=T0, category=LogCategory.DEPARTURE, message="a")
        b = LogEntry(time=T0, category=LogCategory.DEPARTURE, message="b")
        a.data["x"] = 1
        assert b.data == {}


class TestBoatPreset:
    def test_round_trip_with_nested_polar(self) -> None:
        boat = _boat()
        assert BoatPreset.model_validate(boat.model_dump()) == boat


class TestOrdersValidation:
    def test_defaults_are_waypoint_mode(self) -> None:
        orders = Orders()
        assert orders.routing_mode == RoutingMode.WAYPOINT
        assert orders.waypoints == []
        assert orders.sail_plan == SailPlan.FULL
        assert orders.arrival_radius_nm == 2.0

    def test_waypoint_mode_with_empty_waypoints_is_valid(self) -> None:
        # Falls back to the passage destination at the motion layer; not a validation error here.
        Orders(routing_mode=RoutingMode.WAYPOINT, waypoints=[])

    def test_heading_mode_requires_fixed_heading(self) -> None:
        with pytest.raises(ValidationError):
            Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=None)

    @pytest.mark.parametrize("heading", [-1.0, 360.0, 400.0])
    def test_heading_mode_rejects_out_of_range_heading(self, heading: float) -> None:
        with pytest.raises(ValidationError):
            Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=heading)

    def test_heading_mode_accepts_valid_heading(self) -> None:
        orders = Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=270.0)
        assert orders.fixed_heading_deg == 270.0

    @pytest.mark.parametrize("radius", [0.0, 1.0, 1.59])
    def test_arrival_radius_below_floor_rejected(self, radius: float) -> None:
        with pytest.raises(ValidationError):
            Orders(arrival_radius_nm=radius)

    def test_arrival_radius_at_floor_accepted(self) -> None:
        orders = Orders(arrival_radius_nm=1.6)
        assert orders.arrival_radius_nm == 1.6

    def test_round_trip(self) -> None:
        orders = _orders()
        assert Orders.model_validate(orders.model_dump()) == orders

    def test_version_is_locked_to_v0(self) -> None:
        with pytest.raises(ValidationError):
            Orders(version="v1")


class TestPassageParams:
    # Exercises the cross-module forward-reference wiring (state.PassageParams.orders ->
    # engine.orders.Orders), resolved in passage/engine/__init__.py via model_rebuild.
    def test_construct_and_round_trip(self) -> None:
        params = PassageParams(
            boat=_boat(), orders=_orders(), destination=GeoPoint(lat=2.0, lon=2.0),
            seed=42, started_at=T0,
        )
        dumped = params.model_dump()
        assert dumped["orders"]["waypoints"][0] == {"lat": 1.0, "lon": 1.0}
        assert PassageParams.model_validate(dumped) == params


class TestSegmentResult:
    def test_round_trip_with_empty_lists(self) -> None:
        end_state = VesselState(time=T0, position=GeoPoint(lat=0, lon=0), heading_deg=0.0, speed_kn=0.0)
        result = SegmentResult(end_state=end_state, track_points=[], log_entries=[])
        assert SegmentResult.model_validate(result.model_dump()) == result
