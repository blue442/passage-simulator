# CONTRACT — see specs/engine-state.md §4.
#
# NEEDS-JUDGMENT: every polar number below is a plausible-looking placeholder, not a tuned
# value. Structure (breakpoints, monotonic shape) is frozen; the numbers themselves are for a
# later spec session with Steven. Do not "improve" these to make a test look more realistic —
# that is exactly the tuning this ticket is not supposed to do (EXECUTION.md trigger 5).
from passage.engine.polars import PolarTable
from passage.engine.state import BoatPreset

_CRUISER35_POLAR = PolarTable(
    tws_values=[6, 10, 15, 20, 25],
    twa_values=[40, 60, 90, 120, 150, 180],
    boat_speed=[
        [1.9, 2.9, 3.7, 4.1, 4.1],
        [2.5, 3.9, 5.1, 5.6, 5.6],
        [3.0, 4.7, 6.1, 6.8, 6.8],
        [3.4, 5.3, 6.8, 7.5, 7.5],
        [2.9, 4.5, 5.7, 6.4, 6.4],
        [2.2, 3.4, 4.4, 4.9, 4.9],
    ],
)

_PERF45_POLAR = PolarTable(
    tws_values=[6, 10, 15, 20, 25],
    twa_values=[40, 60, 90, 120, 150, 180],
    boat_speed=[
        [2.8, 4.1, 5.2, 5.5, 5.5],
        [3.7, 5.5, 6.9, 7.3, 7.3],
        [4.4, 6.6, 8.3, 8.7, 8.7],
        [4.8, 7.1, 9.0, 9.5, 9.5],
        [4.1, 6.2, 7.9, 8.3, 8.3],
        [3.2, 4.8, 6.1, 6.5, 6.5],
    ],
)

_CAT40_POLAR = PolarTable(
    tws_values=[6, 10, 15, 20, 25],
    twa_values=[40, 60, 90, 120, 150, 180],
    boat_speed=[
        [4.1, 6.4, 8.8, 10.5, 11.7],
        [5.4, 8.4, 11.5, 13.8, 15.3],
        [6.0, 9.4, 12.8, 15.4, 17.1],
        [6.3, 9.9, 13.5, 16.2, 18.0],
        [5.7, 8.9, 12.2, 14.6, 16.2],
        [4.7, 7.4, 10.1, 12.2, 13.5],
    ],
)

BOAT_PRESETS: dict[str, BoatPreset] = {
    "cruiser35": BoatPreset(
        key="cruiser35",
        name="35ft Cruiser",
        hull_length_m=10.7,
        max_hull_speed_kn=7.5,
        polar=_CRUISER35_POLAR,
    ),
    "perf45": BoatPreset(
        key="perf45",
        name="45ft Performance Cruiser",
        hull_length_m=13.7,
        max_hull_speed_kn=9.5,
        polar=_PERF45_POLAR,
    ),
    "cat40": BoatPreset(
        key="cat40",
        name="40ft Cruising Catamaran",
        hull_length_m=12.2,
        max_hull_speed_kn=18.0,
        polar=_CAT40_POLAR,
    ),
}


def get_boat(key: str) -> BoatPreset:
    try:
        return BOAT_PRESETS[key]
    except KeyError:
        raise KeyError(f"unknown boat preset {key!r}; known presets: {sorted(BOAT_PRESETS)}") from None
