# CONTRACT — see specs/engine-state.md §4; specs/golden-fixtures.md GF-1.
import bisect

from pydantic import BaseModel


class PolarTable(BaseModel):
    tws_values: list[float]        # ascending TWS breakpoints (kn), columns
    twa_values: list[float]        # ascending TWA breakpoints (deg, 0..180), rows
    boat_speed: list[list[float]]  # boat_speed[twa_idx][tws_idx] = BSP (kn)


def _axis_interp(values: list[float], x: float) -> tuple[int, int, float]:
    """Given ascending breakpoints, return (lo_idx, hi_idx, frac) to linearly interpolate x
    between values[lo_idx] and values[hi_idx]. Clamps to the nearest edge (frac=0.0,
    lo_idx == hi_idx) outside the breakpoint range — no extrapolation, per
    specs/engine-state.md §4."""
    if x <= values[0]:
        return 0, 0, 0.0
    if x >= values[-1]:
        last = len(values) - 1
        return last, last, 0.0
    lo = bisect.bisect_right(values, x) - 1
    hi = lo + 1
    frac = (x - values[lo]) / (values[hi] - values[lo])
    return lo, hi, frac


def boat_speed(polar: PolarTable, tws_kn: float, twa_deg: float) -> float:
    """Bilinear interpolation in (TWS, TWA). TWA is folded to [0, 180] via abs before lookup
    (port/starboard symmetric). Clamps at the table edges; never extrapolates."""
    twa_deg = abs(twa_deg)
    tws_lo, tws_hi, tws_frac = _axis_interp(polar.tws_values, tws_kn)
    twa_lo, twa_hi, twa_frac = _axis_interp(polar.twa_values, twa_deg)

    table = polar.boat_speed
    v_at_twa_lo = table[twa_lo][tws_lo] * (1 - tws_frac) + table[twa_lo][tws_hi] * tws_frac
    v_at_twa_hi = table[twa_hi][tws_lo] * (1 - tws_frac) + table[twa_hi][tws_hi] * tws_frac
    return v_at_twa_lo * (1 - twa_frac) + v_at_twa_hi * twa_frac
