from datetime import UTC, datetime, timedelta

import pytest

from passage.weather.cache import snap_tile
from passage.weather.sampler import MissingWeatherDataError, build_sampler

H0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
H1 = H0 + timedelta(hours=1)

# Real tile indices for lat=0.0/0.25, lon=0.0/0.25 (TILE_RESOLUTION_DEG=0.25), matching what
# cache.snap_tile would actually produce -- the sampler must bracket using the same formula.
LAT_LO_IDX, LON_LO_IDX, _, _ = snap_tile(0.0, 0.0)
LAT_HI_IDX, LON_HI_IDX, _, _ = snap_tile(0.25, 0.25)

assert (LAT_LO_IDX, LON_LO_IDX) == (360, 720)
assert (LAT_HI_IDX, LON_HI_IDX) == (361, 721)


def _row(lat_idx: int, lon_idx: int, hour: datetime, variables: dict) -> dict:
    return {
        "source": "test", "lat_idx": lat_idx, "lon_idx": lon_idx, "hour_utc": hour,
        "latitude": 0.0, "longitude": 0.0, "variables": variables,
    }


class TestGF8TrilinearCenterValue:
    def test_bilinear_space_linear_time_gives_18(self) -> None:
        # wind_speed_kn per corner, per specs/golden-fixtures.md GF-8:
        #            lon=0.0        lon=0.25
        # lat=0.0    H0=10 H1=20    H0=12 H1=22
        # lat=0.25   H0=14 H1=24    H0=16 H1=26
        wind_speed_by_corner = {
            (LAT_LO_IDX, LON_LO_IDX): (10, 20),
            (LAT_LO_IDX, LON_HI_IDX): (12, 22),
            (LAT_HI_IDX, LON_LO_IDX): (14, 24),
            (LAT_HI_IDX, LON_HI_IDX): (16, 26),
        }
        rows = []
        for (lat_idx, lon_idx), (v_h0, v_h1) in wind_speed_by_corner.items():
            for hour, wind_speed_kn in ((H0, v_h0), (H1, v_h1)):
                rows.append(_row(lat_idx, lon_idx, hour, {
                    "wind_speed_kn": wind_speed_kn, "wind_dir_deg": 90, "gust_kn": 12,
                    "pressure_hpa": 1013, "wave_height_m": 1.0,
                }))

        sampler = build_sampler(rows)
        result = sampler(0.125, 0.125, H0 + timedelta(minutes=30))

        assert result.wind_speed_kn == pytest.approx(18.0, abs=1e-9)


class TestGF8AngleWrap:
    def test_wind_dir_interpolates_as_unit_vectors_not_raw_degrees(self) -> None:
        # Single tile (same value at all 4 spatial corners): H0=350deg, H1=10deg. Interpolating
        # as unit vectors must give ~0/360, NOT 180 (which raw-degree linear interp would give).
        rows = []
        for lat_idx in (LAT_LO_IDX, LAT_HI_IDX):
            for lon_idx in (LON_LO_IDX, LON_HI_IDX):
                for hour, wind_dir_deg in ((H0, 350.0), (H1, 10.0)):
                    rows.append(_row(lat_idx, lon_idx, hour, {
                        "wind_speed_kn": 10.0, "wind_dir_deg": wind_dir_deg, "gust_kn": 12,
                        "pressure_hpa": 1013, "wave_height_m": 1.0,
                    }))

        sampler = build_sampler(rows)
        result = sampler(0.125, 0.125, H0 + timedelta(minutes=30))

        # Accept either 0.0 or 360.0 (the wrap boundary) -- never 180 (the raw-degree-average bug).
        assert result.wind_dir_deg == pytest.approx(0.0, abs=1e-6) or result.wind_dir_deg == pytest.approx(360.0, abs=1e-6)


class TestGF8MissingTileRaises:
    def test_query_outside_loaded_box_raises(self) -> None:
        rows = [
            _row(lat_idx, lon_idx, hour, {
                "wind_speed_kn": 10.0, "wind_dir_deg": 90.0, "gust_kn": 12,
                "pressure_hpa": 1013, "wave_height_m": 1.0,
            })
            for lat_idx in (LAT_LO_IDX, LAT_HI_IDX)
            for lon_idx in (LON_LO_IDX, LON_HI_IDX)
            for hour in (H0, H1)
        ]
        sampler = build_sampler(rows)

        with pytest.raises(MissingWeatherDataError):
            sampler(10.0, 10.0, H0 + timedelta(minutes=30))  # far outside the loaded box

    def test_query_outside_loaded_hour_range_raises(self) -> None:
        rows = [
            _row(lat_idx, lon_idx, H0, {
                "wind_speed_kn": 10.0, "wind_dir_deg": 90.0, "gust_kn": 12,
                "pressure_hpa": 1013, "wave_height_m": 1.0,
            })
            for lat_idx in (LAT_LO_IDX, LAT_HI_IDX)
            for lon_idx in (LON_LO_IDX, LON_HI_IDX)
        ]
        sampler = build_sampler(rows)

        with pytest.raises(MissingWeatherDataError):
            sampler(0.125, 0.125, H0 + timedelta(minutes=30))  # H1 never loaded

    def test_missing_single_field_raises(self) -> None:
        # om-marine data (wave_height_m) never loaded for this tile/hour -- a partial-coverage
        # bug, not just a wholly-missing tile. Must still raise, not default to 0.
        rows = [
            _row(lat_idx, lon_idx, hour, {
                "wind_speed_kn": 10.0, "wind_dir_deg": 90.0, "gust_kn": 12, "pressure_hpa": 1013,
                # wave_height_m intentionally omitted
            })
            for lat_idx in (LAT_LO_IDX, LAT_HI_IDX)
            for lon_idx in (LON_LO_IDX, LON_HI_IDX)
            for hour in (H0, H1)
        ]
        sampler = build_sampler(rows)

        with pytest.raises(MissingWeatherDataError):
            sampler(0.125, 0.125, H0 + timedelta(minutes=30))


class TestCurrentIsAlwaysZero:
    def test_current_fields_are_zero_regardless_of_rows(self) -> None:
        rows = [
            _row(lat_idx, lon_idx, hour, {
                "wind_speed_kn": 10.0, "wind_dir_deg": 90.0, "gust_kn": 12,
                "pressure_hpa": 1013, "wave_height_m": 1.0,
            })
            for lat_idx in (LAT_LO_IDX, LAT_HI_IDX)
            for lon_idx in (LON_LO_IDX, LON_HI_IDX)
            for hour in (H0, H1)
        ]
        sampler = build_sampler(rows)
        result = sampler(0.125, 0.125, H0 + timedelta(minutes=30))
        assert result.current_speed_kn == 0.0
        assert result.current_dir_deg == 0.0
