"""
RMSE helpers for colour-mixing optimization.

Note:
    In the RGBy workflow the optimizer suggests 4D volumes
    ``(R_vol, G_vol, B_vol, water_vol)``, but RMSE is still computed in RGB
    colour space from measured camera output.
"""

import math


def calculate_rmse(
    mixed: tuple[int, int, int],
    target: tuple[int, int, int],
) -> float:
    """
    Calculate the RMSE between a mixed colour and a target colour.

    Args:
        mixed: Measured RGB of the mixed colour (R, G, B), values 0–255.
        target: Target RGB colour (R, G, B), values 0–255.

    Returns:
        RMSE as a float. 0.0 means a perfect match; max is ~147.2 (white vs black).
    """
    r_mix, g_mix, b_mix = mixed
    r_tgt, g_tgt, b_tgt = target

    mse = ((r_mix - r_tgt) ** 2 + (g_mix - g_tgt) ** 2 + (b_mix - b_tgt) ** 2) / 3
    return math.sqrt(mse)


def stop_condition_reached(
    rmse: float,
    iteration: int,
    rmse_threshold: float,
    max_iterations: int,
) -> tuple[bool, str]:
    """
    Check whether the optimization stop condition has been reached.

    Args:
        rmse: Current RMSE value.
        iteration: Current iteration number (1-indexed).
        rmse_threshold: RMSE value at or below which the optimization is considered successful.
        max_iterations: Maximum number of iterations allowed.

    Returns:
        (stopped, reason) — stopped is True if the loop should end,
        reason is a human-readable string explaining why.
    """
    if rmse <= rmse_threshold:
        return True, f"RMSE {rmse:.4f} ≤ threshold {rmse_threshold}"
    if iteration >= max_iterations:
        return True, f"Reached maximum iterations ({max_iterations})"
    return False, ""


def validate_rgby_volumes(
    volumes: tuple[float, float, float, float] | list[float],
    total_volume: float,
    *,
    tolerance_ul: float = 1.0,
) -> tuple[bool, str]:
    """
    Validate an RGBy volume vector against total-volume constraint.

    Args:
        volumes: (R_vol, G_vol, B_vol, water_vol) in µL.
        total_volume: Expected total volume in µL.
        tolerance_ul: Allowed absolute sum error in µL.

    Returns:
        (is_valid, reason). reason is empty when valid.
    """
    if len(volumes) != 4:
        return False, f"Expected 4 volumes (R,G,B,water), got {len(volumes)}"

    total = float(sum(volumes))
    if abs(total - total_volume) > tolerance_ul:
        return False, (
            f"Volumes sum to {total:.2f} µL, expected {total_volume:.2f} µL "
            f"(±{tolerance_ul:.2f} µL)"
        )

    if any(float(v) < 0 for v in volumes):
        return False, "Volumes must be non-negative."

    return True, ""


if __name__ == "__main__":
    # Quick sanity check
    mixed = (200, 100, 50)
    target = (180, 120, 60)
    rmse = calculate_rmse(mixed, target)
    print(f"Mixed:  {mixed}")
    print(f"Target: {target}")
    print(f"RMSE:   {rmse:.4f}")

    stopped, reason = stop_condition_reached(rmse, iteration=3, rmse_threshold=10.0, max_iterations=20)
    print(f"Stop:   {stopped} — {reason}")
