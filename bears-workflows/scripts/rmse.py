"""
RMSE calculation between a mixed colour and a target colour in RGB space.
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
