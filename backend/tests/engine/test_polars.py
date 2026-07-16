import json
from pathlib import Path

import pytest

from passage.engine.boats import BOAT_PRESETS, get_boat
from passage.engine.polars import PolarTable, boat_speed

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def polar_test() -> PolarTable:
    data = json.loads((FIXTURES / "polar_test.json").read_text())
    return PolarTable(
        tws_values=data["tws_values"],
        twa_values=data["twa_values"],
        boat_speed=data["boat_speed"],
    )


class TestBoatSpeedGF1:
    # specs/golden-fixtures.md GF-1. Exact equality (binary-friendly fractions in the fixture).
    @pytest.mark.parametrize(
        "tws,twa,expected",
        [
            (6, 45, 3.0),      # grid corner
            (10, 135, 5.5),    # grid corner
            (8, 90, 5.25),     # linear in tws: 4.0 + 0.5*(6.5-4.0)
            (8, 67.5, 4.625),  # bilinear: tws6->3.5, tws10->5.75, mid->4.625
            (4, 90, 4.0),      # tws below range -> clamp to 6
            (12, 90, 6.5),     # tws above range -> clamp to 10
            (8, -90, 5.25),    # TWA folded by abs -> 90
        ],
    )
    def test_gf1_table(self, polar_test: PolarTable, tws: float, twa: float, expected: float) -> None:
        assert boat_speed(polar_test, tws, twa) == pytest.approx(expected, abs=1e-9)


class TestBoatSpeedEdgeCases:
    def test_twa_below_range_clamps(self, polar_test: PolarTable) -> None:
        # twa_values[0] == 45; below it should clamp to the twa=45 row.
        assert boat_speed(polar_test, 6, 10) == pytest.approx(boat_speed(polar_test, 6, 45), abs=1e-9)

    def test_twa_above_range_clamps(self, polar_test: PolarTable) -> None:
        # twa_values[-1] == 135; above it should clamp to the twa=135 row.
        assert boat_speed(polar_test, 6, 179) == pytest.approx(boat_speed(polar_test, 6, 135), abs=1e-9)

    def test_no_extrapolation_beyond_edges(self, polar_test: PolarTable) -> None:
        far_above = boat_speed(polar_test, 100, 90)
        at_edge = boat_speed(polar_test, 10, 90)
        assert far_above == pytest.approx(at_edge, abs=1e-9)


class TestBoatPresets:
    @pytest.mark.parametrize("key", ["cruiser35", "perf45", "cat40"])
    def test_get_boat_returns_preset(self, key: str) -> None:
        boat = get_boat(key)
        assert boat.key == key
        assert boat.max_hull_speed_kn > 0
        assert boat.polar.boat_speed  # non-empty

    def test_get_boat_raises_on_unknown_key(self) -> None:
        with pytest.raises(KeyError):
            get_boat("nonexistent")

    def test_registry_has_all_three_presets(self) -> None:
        assert set(BOAT_PRESETS) == {"cruiser35", "perf45", "cat40"}

    @pytest.mark.parametrize("key", ["cruiser35", "perf45", "cat40"])
    def test_polar_values_are_non_negative(self, key: str) -> None:
        polar = get_boat(key).polar
        assert all(v >= 0 for row in polar.boat_speed for v in row)

    @pytest.mark.parametrize("key", ["cruiser35", "perf45", "cat40"])
    def test_polar_is_non_decreasing_with_tws(self, key: str) -> None:
        # Sanity check, not tuning: more wind should never mean less boat speed at a fixed TWA.
        polar = get_boat(key).polar
        for row in polar.boat_speed:
            assert row == sorted(row)

    @pytest.mark.parametrize("key", ["cruiser35", "perf45", "cat40"])
    def test_boat_speed_never_exceeds_max_hull_speed(self, key: str) -> None:
        boat = get_boat(key)
        for row in boat.polar.boat_speed:
            for v in row:
                assert v <= boat.max_hull_speed_kn
