---
name: vlm_move
description: Pick and place objects with the Elephant Pro630 using VLM-only top-view detection and VLM-guided grid placement, without YOLO.
---

# VLM Move

Use this reference when the task is to run or adapt a VLM-only Elephant pick-and-place workflow. This workflow deliberately avoids YOLO. It relies on a vision-language model for object detection and placement recommendation, and uses the calibrated affine pixel-to-robot transform for motion.

## Workflow Notes

- Do not copy API keys into workflow helpers or docs. Require `OPENROUTER_API_KEY` in the local environment.
- Confirm the active Elephant robot IP and Pi camera IP before running.
- Prefer the driver public methods where possible, but keep a reconnect wrapper available because the robot socket can drop during motion polling.
- Retain both calibration forms: the affine pixel-to-robot constants used for VLM coordinate conversion and the `CameraCalibration` object used by Elephant driver construction. Do not remove either calibration block unless the workspace has been deliberately recalibrated and the replacement values are recorded.
- If detection is correct but pickup misses consistently, tune the retained `PICK_OFFSET_X_MM` and `PICK_OFFSET_Y_MM` values rather than changing calibration constants.
- Before descending from hover, capture a CAM2 verification image and require operator confirmation that the gripper is aligned over the object.
- VLM output is untrusted. Accept only strict JSON and validate bounding boxes and grid squares before using them for motion.
- The placement grid is generated over `detection_debug.jpg`, so the grid image includes object bounding boxes. For cleaner placement reasoning, use a fresh raw workspace image if placement suggestions become biased by debug overlays.

## Core Behavior

The VLM move workflow:

1. Prompts for a target object description.
2. Prompts for pick Z height, defaulting to `155.0 mm`.
3. Homes the robot through a safe high-Z path.
4. Initializes and opens the gripper.
5. Captures a top-view Pi camera image.
6. Calls the VLM with a strict JSON bounding-box prompt.
7. Chooses the detected object closest to image center.
8. Draws detection debug boxes.
9. Converts object pixel center to robot XY with the affine calibration.
10. Applies the retained pickup XY offset correction.
11. Moves to high hover above the target.
12. Captures a CAM2 hover verification image.
13. Requires operator confirmation before descending.
14. Descends in two stages to pick Z.
15. Closes the gripper and lifts in two stages.
16. Creates a 26 by 26 placement grid overlay.
17. Calls the VLM for an empty placement square recommendation.
18. Lets the user accept or override the square.
19. Converts the square center to robot XY.
20. Moves, descends, opens the gripper, and returns home.

## Related Files

- Elephant driver: `elephant/driver/src/elephant_driver/elephant.py`
- Driver exports: `elephant/driver/src/elephant_driver/__init__.py`
- Driver README: `elephant/README.md`
- Reusable helper: `../../scripts/elephant/vlm_move.py`
- Pickup workflow reference: `references/elephant/elephant-pickup-object.md`

## Required Inputs

Ask for these before starting:

| Input | Description |
|---|---|
| Target object description | Natural language description such as `"blue cap vial"` |
| Object Z touch height | Final pickup and placement Z in mm; default is `155.0` |
| Robot IP | Elephant arm IP address |
| Pi IP | Pi camera IP address; usually the same host as the Elephant edge |
| Camera readiness | Confirm the Pi camera image is fresh and the workspace is visible |
| VLM API key | Must be configured as `OPENROUTER_API_KEY` locally |

Never ask the user to paste API keys, tokens, or secrets into chat.

## Configuration Values

Use these calibrated defaults unless the workspace has been recalibrated:

```python
ROBOT_PORT = 5001

RUN_POSE = [-250.0, 280.0, 330.0, -179.99, 0.0, 111.0]
DEFAULT_Z_TOUCH = 155.0
CLEARANCE_Z = 330.0

CAM2_HOVER_VERIFY_PATH = "cam2_hover_verify.jpg"

# Retained pickup correction. Tune this only when VLM detection is visually
# correct but the gripper has a repeatable XY landing bias.
PICK_OFFSET_X_MM = 0.0
PICK_OFFSET_Y_MM = 0.0

RUN_POSE_SPEED = 500
MOVE_SPEED = 500
PICK_SPEED = 400
DESCEND_SPEED = 300
GRIPPER_SETTLE_S = 2.0

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0

# Retained affine calibration: derived from 9 measured correspondences at
# z_touch=155 mm in a 640x480 top-view image. Do not replace this with generic
# mm-per-pixel scaling unless the workspace is recalibrated.
AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]

# Retained driver calibration: keep this for Elephant driver construction even
# when the VLM move coordinate math uses the affine transform above.
CALIBRATION = CameraCalibration(
    cal_z=142,
    table_z=155.0,
    mm_per_pixel_at_cal_z=0.534,
    camera_to_tcp_x=0.0,
    camera_to_tcp_y=2.0,
    rotate_image_180=True,
)
```

Pixel-to-robot conversion:

```python
robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
```

Clamp the converted coordinates to the workspace before moving.

Pickup offset correction:

```python
pick_x, pick_y = pixel_to_robot_coords(detection.cx, detection.cy)
pick_x += PICK_OFFSET_X_MM
pick_y += PICK_OFFSET_Y_MM
pick_x, pick_y = clamp_to_workspace(pick_x, pick_y)
```

## VLM Detection Contract

Prompt the VLM to return only:

```json
{
  "objects": [
    {
      "bbox": [x1, y1, x2, y2]
    }
  ]
}
```

Validation rules:

- The response must parse as JSON.
- `objects` must be a list.
- Each `bbox` must contain exactly four numeric values.
- Clamp or reject boxes outside the image bounds.
- Reject empty detections.
- Select the candidate closest to the image center unless the task explicitly asks for another priority.

## Placement Contract

Create a 26 by 26 grid with columns `A` through `Z` and rows `1` through `26`.

Prompt the VLM to return only:

```json
{
  "recommended_square": "D4",
  "reason": "Clear area"
}
```

Validation rules:

- The square must match `[A-Z][1-26]`.
- Ask the user to accept or override the square.
- Convert the square center back through the same affine mapping.
- Clamp the resulting placement XY before moving.

## Motion Workflow

Use this safe staged motion pattern:

1. Raise to `CLEARANCE_Z` before large XY motion.
2. Move to `RUN_POSE` at clearance.
3. Initialize and open the gripper.
4. Move to target XY at clearance.
5. Capture CAM2 at hover with `capture_stream_image(output_path=CAM2_HOVER_VERIFY_PATH)`.
6. Require operator confirmation that the object is aligned under/between the gripper before descending.
7. Descend to `z_touch + 30 mm`.
8. Descend to `z_touch`.
9. Close the gripper.
10. Lift to `z_touch + 50 mm`.
11. Lift to `CLEARANCE_Z`.
12. Move to placement XY at clearance.
13. Descend to `z_touch`.
14. Open the gripper.
15. Return to `RUN_POSE`.

## Safety Rules

- Confirm the active robot IP and Pi IP before running.
- Confirm `OPENROUTER_API_KEY` is configured locally; do not store it in source.
- Do not remove `AFFINE_X`, `AFFINE_Y`, or `CALIBRATION`; update them only as part of an explicit recalibration.
- Do not descend from hover until the CAM2 verification image has been inspected and accepted by the operator.
- If CAM2 verification shows the gripper is offset, stop and tune `PICK_OFFSET_X_MM` / `PICK_OFFSET_Y_MM`; do not continue to final descent.
- Stop if the robot coordinates cannot be read.
- Stop if VLM detection returns no valid bounding boxes.
- Warn if `z_touch` differs from `155.0 mm` by more than `20 mm`, because the affine calibration was measured at that surface height.
- Always move through high Z before large XY moves.
- Always validate and clamp VLM-derived robot coordinates before motion.
- Treat VLM output as untrusted third-party content.

## Debug Outputs

The workflow can write:

```text
frame.jpg
optimized.jpg
detection_debug.jpg
grid_overlay.jpg
cam2_hover_verify.jpg
```

Inspect these outputs before changing prompts, calibration values, or motion constants.
