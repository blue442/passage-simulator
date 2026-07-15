# NEEDS-JUDGMENT — placeholder values, do not tune in an implementation session.
# See specs/engine-state.md §8. Structure is frozen; values are tuned in a later spec
# session with Steven.
UPWIND_LIMIT_DEG: float = 40.0      # closest TWA the boat will point
DOWNWIND_LIMIT_DEG: float = 170.0   # deepest TWA before forcing a gybe angle
LEEWAY_COEFF: float = 0.0           # deg of leeway per unit; 0 disables leeway in Phase 1
TACK_HYSTERESIS_DEG: float = 0.0    # 0 = none; raise only via a spec decision if oscillation appears


def wave_drag_factor(wave_height_m: float) -> float:
    # Multiplicative BSP factor in (0,1]. Placeholder: mild linear knockdown, floored.
    return max(0.6, 1.0 - 0.02 * wave_height_m)
