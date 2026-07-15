# CONTRACT — see specs/engine-state.md §4.
#
# Only the PolarTable model is defined here as part of T1.3 (state.py's BoatPreset needs it
# for a direct, non-circular import). The `boat_speed()` bilinear-interpolation function and
# `passage/engine/boats.py`'s preset registry are T1.4's job — do not add them here yet.
from pydantic import BaseModel


class PolarTable(BaseModel):
    tws_values: list[float]        # ascending TWS breakpoints (kn), columns
    twa_values: list[float]        # ascending TWA breakpoints (deg, 0..180), rows
    boat_speed: list[list[float]]  # boat_speed[twa_idx][tws_idx] = BSP (kn)
