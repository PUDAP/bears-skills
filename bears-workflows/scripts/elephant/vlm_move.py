"""VLM-only Elephant pick-and-place helpers.

Configure OPENROUTER_API_KEY locally before using the VLM helpers.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass

import cv2
from openai import OpenAI

from elephant_driver import CameraCalibration, CameraConfig, ViewerConfig
from elephant_driver.elephant import (
    DEFAULT_GRIPPER_SETTLE_S,
    DEFAULT_SCAN_COORDS,
    DEFAULT_SPEED,
)


ROBOT_IP = "192.168.50.129"
PI_IP = "192.168.50.129"

VLM_MODEL = "openai/gpt-5.5"
VLM_TIMEOUT_S = 60
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

RUN_POSE = list(DEFAULT_SCAN_COORDS)
DEFAULT_Z_TOUCH = 155.0
CLEARANCE_Z = RUN_POSE[2]

RUN_POSE_SPEED = DEFAULT_SPEED
MOVE_SPEED = DEFAULT_SPEED
PICK_SPEED = 400
DESCEND_SPEED = 300
GRIPPER_SETTLE_S = DEFAULT_GRIPPER_SETTLE_S

Z_REACH_TOL_MM = 5.0
Z_REACH_TIMEOUT_S = 60.0
XY_REACH_TOL_MM = 3.0
XY_REACH_TIMEOUT_S = 15.0

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0

# Affine calibration derived from 9 measured correspondences at z_touch=155 mm
# in a 640x480 top-view image. Do not remove or replace this with generic
# mm-per-pixel scaling unless the workspace is recalibrated.
AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]

# Retain the driver calibration object as well as the affine calibration. Some
# Elephant driver paths expect a CameraCalibration instance even though VLM move
# coordinate conversion uses pixel_to_robot_coords() below.
CALIBRATION = CameraCalibration(
    cal_z=142,
    table_z=DEFAULT_Z_TOUCH,
    mm_per_pixel_at_cal_z=0.534,
    camera_to_tcp_x=0.0,
    camera_to_tcp_y=2.0,
    rotate_image_180=True,
)


def make_camera_config(
    *,
    pi_ip: str = PI_IP,
    local_image_dir: str | os.PathLike[str] = ".",
) -> CameraConfig:
    return ViewerConfig(
        pi_ip=pi_ip,
        pi_local_image_dir=str(local_image_dir),
    ).pi_camera_config()


@dataclass(frozen=True)
class Detection:
    bbox: tuple[int, int, int, int]
    cx: int
    cy: int
    image_path: str
    image_size: tuple[int, int]
    image_center: tuple[int, int]
    all_bboxes: list[list[int]]


def get_openrouter_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in the local environment.")
    return key


def get_vlm_client() -> OpenAI:
    return OpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=get_openrouter_key(),
        timeout=VLM_TIMEOUT_S,
    )


def extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise RuntimeError("VLM returned empty content.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass

    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    preview = text if len(text) <= 500 else text[:500] + "..."
    raise RuntimeError(f"Could not parse JSON from VLM response. Raw content:\n{preview}")


def call_vlm_json(prompt: str, image_path: str, *, model: str = VLM_MODEL) -> dict:
    with open(image_path, "rb") as image_file:
        img_b64 = base64.b64encode(image_file.read()).decode("ascii")

    response = get_vlm_client().chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"},
                    },
                ],
            }
        ],
    )
    return extract_json_object(response.choices[0].message.content or "")


def detect_object(object_name: str, image_path: str, *, model: str = VLM_MODEL) -> Detection:
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError(f"Failed to load image: {image_path}")

    height, width = img.shape[:2]
    image_center = (width // 2, height // 2)
    prompt = (
        "You are a precision vision detector for robotic manipulation.\n\n"
        f"Target object:\n{object_name}\n\n"
        "Find ALL visible instances. Return ONLY valid JSON:\n\n"
        '{\n  "objects": [{"bbox":[x1,y1,x2,y2]}]\n}\n\n'
        "Rules:\n"
        "- Tight bounding boxes, integer coordinates inside image bounds.\n"
        "- Do NOT merge multiple objects into one box.\n"
        '- If none found: {"objects":[]}\n'
        f"\nImage: {width}x{height} pixels."
    )

    result = call_vlm_json(prompt, image_path, model=model)
    candidates = result.get("objects", [])
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError(f"No objects detected for: {object_name}")

    best: tuple[int, int, int, int, int, int] | None = None
    best_dist = float("inf")
    all_bboxes: list[list[int]] = []

    for obj in candidates:
        bbox = obj.get("bbox") if isinstance(obj, dict) else None
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox]
        x1 = max(0, min(width - 1, x1))
        x2 = max(0, min(width - 1, x2))
        y1 = max(0, min(height - 1, y1))
        y2 = max(0, min(height - 1, y2))
        if x2 <= x1 or y2 <= y1:
            continue

        all_bboxes.append([x1, y1, x2, y2])
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        dist = (cx - image_center[0]) ** 2 + (cy - image_center[1]) ** 2
        if dist < best_dist:
            best_dist = dist
            best = (x1, y1, x2, y2, cx, cy)

    if best is None:
        raise RuntimeError("No valid bounding boxes in VLM response.")

    x1, y1, x2, y2, cx, cy = best
    return Detection(
        bbox=(x1, y1, x2, y2),
        cx=cx,
        cy=cy,
        image_path=image_path,
        image_size=(width, height),
        image_center=image_center,
        all_bboxes=all_bboxes,
    )


def draw_detection(detection: Detection, save_path: str | os.PathLike[str]) -> str:
    img = cv2.imread(detection.image_path)
    if img is None:
        raise RuntimeError(f"Failed to load image: {detection.image_path}")

    for bbox in detection.all_bboxes:
        x1, y1, x2, y2 = bbox
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 255), 2)

    x1, y1, x2, y2 = detection.bbox
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 3)
    cv2.circle(img, (detection.cx, detection.cy), 6, (0, 0, 255), -1)
    cv2.drawMarker(img, detection.image_center, (255, 0, 0), cv2.MARKER_CROSS, 20, 2)

    cv2.imwrite(str(save_path), img)
    return str(save_path)


def pixel_to_robot_coords(px: int, py: int) -> tuple[float, float]:
    """Convert image pixels to robot XY using the retained affine calibration."""
    robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
    robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
    return robot_x, robot_y


def clamp_to_workspace(x: float, y: float) -> tuple[float, float]:
    return (
        max(ROBOT_X_MIN, min(ROBOT_X_MAX, x)),
        max(ROBOT_Y_MIN, min(ROBOT_Y_MAX, y)),
    )


def target_from_detection(detection: Detection) -> tuple[float, float]:
    return clamp_to_workspace(*pixel_to_robot_coords(detection.cx, detection.cy))


def validate_grid_square(square: str) -> str:
    value = str(square or "").strip().upper()
    if not re.fullmatch(r"[A-Z](?:[1-9]|1[0-9]|2[0-6])", value):
        raise RuntimeError(f"Invalid grid square: {square!r}")
    return value


def grid_square_to_pixel_center(
    square: str,
    image_size: tuple[int, int],
    *,
    grid_size: int = 26,
) -> tuple[int, int]:
    square = validate_grid_square(square)
    width, height = image_size
    cell_w = width // grid_size
    cell_h = height // grid_size
    col_idx = ord(square[0]) - ord("A")
    row_idx = int(square[1:]) - 1
    return col_idx * cell_w + cell_w // 2, row_idx * cell_h + cell_h // 2
