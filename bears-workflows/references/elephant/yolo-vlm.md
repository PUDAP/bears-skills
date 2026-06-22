---
name: elephant-yolo-vlm
description: Run the laptop-only Elephant YOLO/VLM pick workflow with Pi target selection, front cam/side cam alignment, and optional VLA alignment suggestions.
---

# Elephant YOLO/VLM

Use this reference when the task is to run the laptop-only Elephant YOLO/VLM
pick workflow.

This workflow follows the launcher at
`bears-skills/bears-workflows/scripts/elephant/yolo_vlm.py`, which delegates to
the operational Elephant runner. It uses the Elephant machine reference for
machine constraints, motion safety, gripper rules, and camera route naming.

## Related Reference

- Machine reference: `../../../bears-machines/references/elephant.md`

## Run Commands

Run the workflow through the wrapper:

```bash
python bears-skills/bears-workflows/scripts/elephant/yolo_vlm.py
```

Check the runner and environment without starting hardware:

```bash
python bears-skills/bears-workflows/scripts/elephant/yolo_vlm.py --check
```

## Core Workflow

The runner performs this sequence:

1. Loads local `.env` from the `elephant/` folder.
2. Starts local SSH tunnels through the mini PC to the Pi and robot.
3. Verifies the robot tunnel on `LOCAL_ROBOT_PORT`.
4. Starts or verifies the Pi/CAM0 snapshot server.
5. Verifies MediaMTX front cam and side cam streams.
6. Starts the local combined raw/YOLO viewer.
7. Prompts for target object description.
8. Prompts for `z_touch`, default `155.0 mm`.
9. Preloads the YOLO model.
10. Connects to the Elephant robot through the local robot tunnel.
11. Moves to scan/run position.
12. Initializes and opens the electric gripper.
13. Captures a fresh Pi/CAM0 image.
14. Counts the initial visible target objects once with VLM.
15. Runs YOLO detection and VLM marker reasoning to select the next target.
16. Converts the selected Pi/CAM0 pixel center to robot XY with affine
    calibration.
17. Moves above the object at scan Z.
18. Descends only to alignment height, `z_touch + 15 mm`.
19. Runs front cam tape-edge alignment and side cam depth alignment.
20. Optionally uses VLA for small suggested X/Y alignment corrections.
21. Requires final human confirmation before descending to `z_touch`.
22. Descends, closes the gripper, lifts, moves to place, releases, and returns
    to scan.
23. Repeats until the initial planned target count has been picked or detection
    fails.

## Required Inputs

Confirm these before running:

| Input | Description |
|---|---|
| Target object description | Natural language target such as `"blue cap vial"` |
| `z_touch` | Final pickup Z in mm; default is `155.0` |
| Camera readiness | Pi/CAM0, front cam, and side cam streams must be visible and fresh |
| Robot readiness | Robot powered, reachable, and E-stop released |
| Model files | YOLO weights and optional VLA checkpoint must exist locally |
| API key readiness | Confirm `OPENROUTER_API_KEY` is present in `elephant/edge/.env` |

Never ask the user to paste API keys, passwords, or tokens into chat.

## Environment

The wrapper `--check` reports these required values. It checks
`OPENROUTER_API_KEY` from the environment or `elephant/edge/.env` without
printing the secret value:

```text
OPENROUTER_API_KEY
MINIPC_SSH_HOST
PI_HOST_FROM_MINIPC
LOCAL_PI_SSH_PORT
LOCAL_CAM0_PORT
LOCAL_ROBOT_PORT
ELEPHANT_COMBINED_VIEWER_PORT
ELEPHANT_FRONT_STREAM_URL
ELEPHANT_SIDE_STREAM_URL
```

Optional viewer/browser overrides:

```text
ELEPHANT_COMBINED_VIEWER_URL
ELEPHANT_FRONT_BROWSER_URL
ELEPHANT_SIDE_BROWSER_URL
```

The operational runner loads both `elephant/.env` and `elephant/edge/.env`.
It also supports local credential variables such as
`MINIPC_SSH_USERNAME`, `MINIPC_SSH_PASSWORD`, `PI_USERNAME`, and `PI_PASSWORD`
from the local environment or `.env`. Do not store secrets in this skill text.

## Camera Naming

Use the same names as `elephant_driver.combined_viewer`:

| Workflow name | Meaning |
|---|---|
| Pi or Pi/CAM0 | Top-view Pi camera used for object detection and VLM target selection |
| Front cam | Front RTSP stream, configured by `ELEPHANT_FRONT_STREAM_URL` |
| Side cam | Side RTSP stream, configured by `ELEPHANT_SIDE_STREAM_URL` |

The runner keeps some internal `CAM2` and `CAM3` variable names for backward
compatibility, but user-facing workflow text should use front cam and side cam.

## Combined Viewer

The combined viewer route names follow `elephant_driver.combined_viewer`:

```text
Combined viewer:       <base>
Pi raw live:           <base>/pi
Pi YOLO live:          <base>/pi_yolo
Pi raw snapshot:       <base>/snapshot/pi
Pi YOLO snapshot:      <base>/snapshot/pi_yolo
Front cam raw live:    <base>/front
Front cam YOLO live:   <base>/front_yolo
Front cam raw shot:    <base>/snapshot/front
Front cam YOLO shot:   <base>/snapshot/front_yolo
Side cam raw live:     <base>/side
Side cam YOLO live:    <base>/side_yolo
Side cam raw shot:     <base>/snapshot/side
Side cam YOLO shot:    <base>/snapshot/side_yolo
```

`<base>` comes from `ELEPHANT_COMBINED_VIEWER_URL` when set. Otherwise it is
constructed from localhost and `ELEPHANT_COMBINED_VIEWER_PORT`. The code uses
the Elephant driver default combined-viewer port when no override is set.

## Calibration Values

Use the retained calibration below unless the workspace is explicitly
recalibrated:

```python
SCAN_POSITION = [-250, 280.0, 330, -179.730594, -0.396744, 110.994829]
PLACE_POSITION = [-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]
DEFAULT_Z_TOUCH = 155.0

AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0
```

Pixel-to-robot conversion:

```python
robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
```

Clamp converted XY values to the workspace before motion.

## Alignment Rules

- Front cam alignment compares the target center to the center between the two
  inner tape edges on the gripper.
- Side cam alignment checks depth center alignment between the target and the
  side-gripper reference.
- Final pick requires both front cam and side cam alignment, or an explicit
  human override inside the runner.
- VLA alignment is suggestion-gated; it predicts small X/Y corrections, but
  closing still depends on YOLO alignment plus final human confirmation.
- Do not descend to `z_touch` or close the gripper until the final confirmation
  prompt is accepted.

## Safety Rules

- Run this workflow only on the laptop controlling the Elephant camera/tunnel
  stack.
- Do not manually start the old CAM0 server, two-camera livestream test, or
  separate Flask camera mode while this runner owns the camera stack.
- Stop if Pi/CAM0, front cam, or side cam frames are stale.
- Stop if YOLO/VLM cannot select a valid target.
- Stop if the front cam cannot see the target and tape markers.
- Stop if the side cam cannot see the target and side-gripper reference.
- Keep alignment corrections small; use one suggested move at a time unless a
  human operator explicitly chooses otherwise.
- Always return to scan/run position after a completed pick/place or abort.

## Debug Outputs

The workflow may write these debug images during a run:

```text
optimized.jpg
yolo_overlay.jpg
marker_debug.jpg
detection_debug.jpg
target_reference_crop.jpg
logitech_yolo_overlay.jpg
grip_verify.jpg
cam3_side_verify.jpg
```

Inspect these before changing calibration, thresholds, prompts, or alignment
logic.
