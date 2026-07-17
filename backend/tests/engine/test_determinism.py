from datetime import UTC, datetime, timedelta

from passage.engine.boats import get_boat
from passage.engine.constants import STEP
from passage.engine.orders import Orders, RoutingMode
from passage.engine.polars import PolarTable
from passage.engine.simulate import simulate_segment
from passage.engine.state import GeoPoint, PassageParams, VesselState, WeatherSample

T0 = datetime(2026, 1, 1, tzinfo=UTC)

POLAR_TEST = PolarTable(
    tws_values=[6, 10],
    twa_values=[45, 90, 135],
    boat_speed=[[3.0, 5.0], [4.0, 6.5], [3.5, 5.5]],
)


class _AlwaysWater:
    def is_water(self, lat: float, lon: float) -> bool:
        return True


def _boat():
    boat = get_boat("cruiser35")
    return boat.model_copy(update={"polar": POLAR_TEST})


def _analytic_weather(lat: float, lon: float, time: datetime) -> WeatherSample:
    # No cache, no network: a pure closure, isolating the stepping core per GF-6.
    return WeatherSample(
        wind_speed_kn=15, wind_dir_deg=270, gust_kn=18, pressure_hpa=1013,
        wave_height_m=1.0, current_speed_kn=0.0, current_dir_deg=0.0,
    )


def _run_chunked(params: PassageParams, start: VesselState, land, until_boundaries):
    state = start
    track_points = []
    for until in until_boundaries:
        result = simulate_segment(params, state, _analytic_weather, land, until)
        track_points.extend(result.track_points)
        state = result.end_state
    return track_points, state


class TestGF6ChunkInvariance:
    def test_one_four_and_144_chunk_variants_are_bit_identical(self) -> None:
        # HEADING mode (broad reach, unclamped: TWA=|angular_diff(45,270)|=135, inside
        # [40,170]) isolates the stepping core from waypoint-advance logic entirely, per GF-6's
        # intent. Destination is far enough away that arrival never fires in 24h of sailing.
        orders = Orders(routing_mode=RoutingMode.HEADING, fixed_heading_deg=45.0)
        destination = GeoPoint(lat=50.0, lon=50.0)
        start = VesselState(time=T0, position=GeoPoint(lat=0.0, lon=0.0), heading_deg=0.0, speed_kn=0.0)
        params = PassageParams(boat=_boat(), orders=orders, destination=destination, seed=1, started_at=T0)
        land = _AlwaysWater()

        one_chunk = [T0 + timedelta(hours=24)]
        four_chunks = [T0 + timedelta(hours=h) for h in (6, 12, 18, 24)]
        tiny_chunks = [T0 + i * STEP for i in range(1, 145)]

        one_points, one_end = _run_chunked(params, start, land, one_chunk)
        four_points, four_end = _run_chunked(params, start, land, four_chunks)
        tiny_points, tiny_end = _run_chunked(params, start, land, tiny_chunks)

        assert len(one_points) == len(four_points) == len(tiny_points) == 144
        assert one_points == four_points
        assert four_points == tiny_points
        assert one_end == four_end == tiny_end
