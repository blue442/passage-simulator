import pytest

from passage.engine.state import GeoPoint
from passage.geo import HighLatitudeError, distance_nm, initial_bearing_deg, normalize_lon, offset


def gp(lat: float, lon: float) -> GeoPoint:
    return GeoPoint(lat=lat, lon=lon)


class TestDistanceAndBearingGF2:
    # specs/golden-fixtures.md GF-2. EARTH_RADIUS_NM = 3437.7468 (= 60*180/pi) makes the
    # meridian/equator rows exactly 60.0 nm/degree, consistent with "1 deg = 60 nm exactly".
    def test_one_degree_north(self) -> None:
        a, b = gp(0, 0), gp(1, 0)
        assert distance_nm(a, b) == pytest.approx(60.0, abs=1e-6)
        assert initial_bearing_deg(a, b) == pytest.approx(0.0, abs=1e-9)

    def test_one_degree_east(self) -> None:
        a, b = gp(0, 0), gp(0, 1)
        assert distance_nm(a, b) == pytest.approx(60.0, abs=1e-3)
        assert initial_bearing_deg(a, b) == pytest.approx(90.0, abs=1e-9)

    def test_one_degree_south(self) -> None:
        a, b = gp(0, 0), gp(-1, 0)
        assert distance_nm(a, b) == pytest.approx(60.0, abs=1e-6)
        assert initial_bearing_deg(a, b) == pytest.approx(180.0, abs=1e-9)

    def test_one_degree_west(self) -> None:
        a, b = gp(0, 0), gp(0, -1)
        assert distance_nm(a, b) == pytest.approx(60.0, abs=1e-3)
        assert initial_bearing_deg(a, b) == pytest.approx(270.0, abs=1e-9)

    def test_diagonal(self) -> None:
        # compute & freeze (specs/golden-fixtures.md GF-2)
        a, b = gp(0, 0), gp(1, 1)
        assert distance_nm(a, b) == pytest.approx(84.8506604, abs=1e-3)
        assert initial_bearing_deg(a, b) == pytest.approx(44.9956365, abs=1e-2)


class TestOffsetAntimeridian:
    def test_antimeridian_wraps(self) -> None:
        # compute & freeze (specs/golden-fixtures.md GF-2)
        dest = offset(gp(0, 179.9), 90, 60)
        assert dest.lat == pytest.approx(0.0, abs=1e-9)
        assert dest.lon == pytest.approx(-179.1, abs=1e-6)
        assert -180.0 <= dest.lon < 180.0


class TestOffsetRoundTrip:
    def test_short_hop_matches_distance_and_bearing(self) -> None:
        start = gp(10.0, -50.0)
        dest = offset(start, 30.0, 100.0)
        assert distance_nm(start, dest) == pytest.approx(100.0, abs=1e-6)
        assert initial_bearing_deg(start, dest) == pytest.approx(30.0, abs=1e-6)


class TestNormalizeLon:
    @pytest.mark.parametrize(
        "raw,expected",
        [(0.0, 0.0), (180.0, -180.0), (-180.0, -180.0), (359.9, -0.1), (-359.9, 0.1), (540.0, -180.0)],
    )
    def test_wraps_into_range(self, raw: float, expected: float) -> None:
        assert normalize_lon(raw) == pytest.approx(expected, abs=1e-9)
        assert -180.0 <= normalize_lon(raw) < 180.0


class TestHighLatitudeEscalation:
    def test_distance_nm_rejects_high_latitude_point(self) -> None:
        with pytest.raises(HighLatitudeError):
            distance_nm(gp(86.0, 0), gp(0, 0))
        with pytest.raises(HighLatitudeError):
            distance_nm(gp(0, 0), gp(-86.0, 0))

    def test_initial_bearing_rejects_high_latitude_point(self) -> None:
        with pytest.raises(HighLatitudeError):
            initial_bearing_deg(gp(86.0, 0), gp(0, 0))

    def test_distance_nm_accepts_boundary_85(self) -> None:
        # |lat| > 85 escalates; exactly 85 does not.
        distance_nm(gp(85.0, 0), gp(84.0, 0))

    def test_offset_rejects_high_latitude_start(self) -> None:
        with pytest.raises(HighLatitudeError):
            offset(gp(86.0, 0), 0.0, 60.0)

    def test_offset_rejects_high_latitude_destination(self) -> None:
        # Heading due north from 80N for 600nm reaches the pole exactly.
        with pytest.raises(HighLatitudeError):
            offset(gp(80.0, 0), 0.0, 600.0)

    def test_offset_rejects_mid_path_pole_crossing_even_with_innocuous_endpoint(self) -> None:
        # From 70N on a near-meridional course (bearing 10), 6000nm sweeps through ~86.6N
        # (a genuine pole-crossing vertex) before landing back down around 9.7N. Endpoint-only
        # checks (start=70N, end~9.7N) would both look "safe" and silently return garbage.
        with pytest.raises(HighLatitudeError):
            offset(gp(70.0, 0), 10.0, 6000.0)

    def test_offset_accepts_moderate_course_with_no_crossing(self) -> None:
        offset(gp(45.0, 0), 45.0, 500.0)

    def test_offset_accepts_equatorial_eastbound_long_hop(self) -> None:
        # Heading due east from the equator stays on the equator regardless of distance.
        dest = offset(gp(0.0, 0.0), 90.0, 5000.0)
        assert dest.lat == pytest.approx(0.0, abs=1e-9)
