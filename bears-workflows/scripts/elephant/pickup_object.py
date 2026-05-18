"""Motion and calibration helpers for Elephant object pickup workflows."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from elephant_driver import Elephant, Pose6D


ROBOT_IP = "192.168.50.128"
ROBOT_PORT = 5001

SCAN_POSITION = [-250.0, 280.0, 330.0, -179.730594, -0.396744, 110.994829]
PLACE_POSITION = [-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]

DEFAULT_Z_TOUCH = 155.0
MOVE_SPEED = 220
PICK_SPEED = 180
DESCEND_SPEED = 100
LIFT_MM = 60.0
GRIPPER_SETTLE_S = 1.2

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0
PLACE_IGNORE_RADIUS_MM = 35.0

AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    cx: int
    cy: int
    image_path: str
    source: str = "vision"
    cls_name: str = ""
    confidence: float = 0.0


def pixel_to_robot_coords(px: int, py: int) -> tuple[float, float]:
    robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
    robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
    return robot_x, robot_y


def clamp_to_workspace(x: float, y: float) -> tuple[float, float]:
    return (
        max(ROBOT_X_MIN, min(ROBOT_X_MAX, x)),
        max(ROBOT_Y_MIN, min(ROBOT_Y_MAX, y)),
    )


def is_near_place_position(x: float, y: float) -> bool:
    dx = float(x) - PLACE_POSITION[0]
    dy = float(y) - PLACE_POSITION[1]
    return (dx * dx + dy * dy) ** 0.5 <= PLACE_IGNORE_RADIUS_MM


def get_stacked_place_position(place_count: int) -> list[float]:
    pose = PLACE_POSITION.copy()
    pose[0] = PLACE_POSITION[0] - (30.0 * int(place_count))
    return pose


def safe_open_gripper(arm: Elephant, *, settle_s: float = GRIPPER_SETTLE_S) -> None:
    try:
        arm.open_gripper(settle_s=settle_s)
    except TypeError:
        arm.open_gripper()


def safe_close_gripper(arm: Elephant, *, settle_s: float = GRIPPER_SETTLE_S) -> None:
    try:
        arm.close_gripper(settle_s=settle_s)
    except TypeError:
        arm.close_gripper()


def wait_until_reached(
    arm: Elephant,
    target: Pose6D,
    *,
    xy_tol: float = 5.0,
    z_tol: float = 8.0,
    timeout_s: float = 180.0,
    poll_s: float = 0.35,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        coords = arm.get_coords()
        if coords and len(coords) >= 3:
            dx = float(coords[0]) - target.x
            dy = float(coords[1]) - target.y
            dz = float(coords[2]) - target.z
            if (dx * dx + dy * dy) ** 0.5 <= xy_tol and abs(dz) <= z_tol:
                return True
        time.sleep(poll_s)
    return False


def current_pose_or(arm: Elephant, fallback: Pose6D) -> Pose6D:
    coords = arm.get_coords()
    if coords and len(coords) >= 6:
        return Pose6D.from_any(coords[:6])
    return fallback


def move_pose(
    arm: Elephant,
    pose: Pose6D,
    speed: int,
    *,
    wait: bool = True,
    timeout_s: float = 120.0,
    keep_current_rotation: bool = True,
) -> bool:
    safe_pose = pose
    if keep_current_rotation:
        coords = arm.get_coords()
        if coords and len(coords) >= 6:
            safe_pose = pose._replace(rx=coords[3], ry=coords[4], rz=coords[5])

    arm.move(safe_pose, speed=speed)
    if not wait:
        time.sleep(0.35)
        return True
    ok = wait_until_reached(arm, safe_pose, timeout_s=timeout_s)
    time.sleep(0.35)
    return ok


def ensure_run_position(arm: Elephant) -> None:
    coords = arm.get_coords()
    if not coords or len(coords) < 6:
        raise RuntimeError("Cannot read Elephant robot coordinates.")

    run_pose = Pose6D.from_any(SCAN_POSITION)
    already_at_run = (
        abs(float(coords[0]) - run_pose.x) <= 5.0
        and abs(float(coords[1]) - run_pose.y) <= 5.0
        and abs(float(coords[2]) - run_pose.z) <= 8.0
    )
    if already_at_run:
        return

    if abs(float(coords[2]) - run_pose.z) > 8.0:
        safe_raise = Pose6D.from_any([
            coords[0],
            coords[1],
            run_pose.z,
            coords[3],
            coords[4],
            coords[5],
        ])
        move_pose(
            arm,
            safe_raise,
            MOVE_SPEED,
            timeout_s=180.0,
            keep_current_rotation=False,
        )

    move_pose(
        arm,
        run_pose,
        MOVE_SPEED,
        timeout_s=180.0,
        keep_current_rotation=False,
    )


def target_from_detection(detection: Detection) -> tuple[float, float]:
    pick_x, pick_y = pixel_to_robot_coords(detection.cx, detection.cy)
    return clamp_to_workspace(pick_x, pick_y)


def pick_after_alignment(
    arm: Elephant,
    *,
    pick_x: float,
    pick_y: float,
    z_touch: float = DEFAULT_Z_TOUCH,
    place_count: int = 0,
) -> dict[str, Any]:
    """Execute the motion sequence after visual alignment is confirmed.

    This function assumes the caller has already moved to alignment height and
    confirmed CAM2 gripper alignment.
    """
    refined = arm.get_coords()
    if not refined or len(refined) < 6:
        refined = [pick_x, pick_y, z_touch + 15.0, -179.99, 0.0, 111.0]

    pick_pose = Pose6D.from_any([refined[0], refined[1], z_touch, refined[3], refined[4], refined[5]])
    move_pose(arm, pick_pose, DESCEND_SPEED, timeout_s=120.0)
    safe_close_gripper(arm)

    lift_pose = pick_pose._replace(z=SCAN_POSITION[2])
    move_pose(arm, lift_pose, PICK_SPEED, timeout_s=120.0)
    ensure_run_position(arm)

    place_target = Pose6D.from_any(get_stacked_place_position(place_count))
    place_above = place_target._replace(z=place_target.z + LIFT_MM)
    move_pose(arm, place_above, MOVE_SPEED, timeout_s=120.0)

    current = arm.get_coords()
    if current and len(current) >= 6:
        straight_place = Pose6D.from_any([
            current[0],
            current[1],
            place_target.z,
            current[3],
            current[4],
            current[5],
        ])
    else:
        straight_place = place_target

    move_pose(arm, straight_place, DESCEND_SPEED, timeout_s=120.0)
    safe_open_gripper(arm)

    current = arm.get_coords()
    if current and len(current) >= 6:
        safe_raise = Pose6D.from_any([
            current[0],
            current[1],
            place_above.z,
            current[3],
            current[4],
            current[5],
        ])
    else:
        safe_raise = place_above
    move_pose(arm, safe_raise, PICK_SPEED, timeout_s=120.0)
    ensure_run_position(arm)

    return {
        "picked": True,
        "pick_xy": (pick_x, pick_y),
        "place_pose": place_target.as_list(),
    }

