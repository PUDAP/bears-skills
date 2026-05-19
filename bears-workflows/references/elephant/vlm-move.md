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
10. Moves to high hover above the target.
11. Descends in two stages to pick Z.
12. Closes the gripper and lifts in two stages.
13. Creates a 26 by 26 placement grid overlay.
14. Calls the VLM for an empty placement square recommendation.
15. Lets the user accept or override the square.
16. Converts the square center to robot XY.
17. Moves, descends, opens the gripper, and returns home.

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

RUN_POSE_SPEED = 500
MOVE_SPEED = 500
PICK_SPEED = 400
DESCEND_SPEED = 300
GRIPPER_SETTLE_S = 2.0

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0

AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]
```

Pixel-to-robot conversion:

```python
robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
```

Clamp the converted coordinates to the workspace before moving.

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
5. Descend to `z_touch + 30 mm`.
6. Descend to `z_touch`.
7. Close the gripper.
8. Lift to `z_touch + 50 mm`.
9. Lift to `CLEARANCE_Z`.
10. Move to placement XY at clearance.
11. Descend to `z_touch`.
12. Open the gripper.
13. Return to `RUN_POSE`.

## Safety Rules

- Confirm the active robot IP and Pi IP before running.
- Confirm `OPENROUTER_API_KEY` is configured locally; do not store it in source.
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
```

Inspect these outputs before changing prompts, calibration values, or motion constants.
