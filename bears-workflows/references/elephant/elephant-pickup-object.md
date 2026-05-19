---
name: elephant-pickup-object
description: Detect, align, pick, lift, and place target objects with the Elephant Pro630 using Pi camera YOLO/VLM selection and CAM2 gripper alignment.
---

# Elephant Pickup Object

Use this reference when the task is to pick up an object with the Elephant Pro630 using the `elephant_driver` package.

## Core Behavior

The pickup workflow repeatedly:

1. Moves the robot to a scan position.
2. Captures Pi camera top-view image.
3. Uses YOLO plus VLM to choose the target object.
4. Converts the selected pixel center to robot XY.
5. Moves above the target.
6. Uses CAM2 alignment before descending.
7. Descends to the object Z height.
8. Closes the gripper.
9. Lifts to safe scan height.
10. Moves to the place position and releases.

## Related References

- Elephant driver: `elephant/driver/src/elephant_driver/elephant.py`
- Driver exports: `elephant/driver/src/elephant_driver/__init__.py`
- Driver README: `elephant/README.md`
- Pickup helper script: `../../scripts/elephant/pickup_object.py`
- YOLO alignment helper script: `../../scripts/elephant/yolo_alignment.py`
- Combined viewer module: `elephant_driver.combined_viewer`
- Alignment reference: `references/elephant/yolo-alignment.md`

Workflow functions to implement or reuse:

- `main()`
- `detect_object(object_name, image_path)`
- `capture_fresh_image(arm)`
- `pixel_to_robot_coords(px, py)`
- `ensure_run_position(arm)`
- `move_pose(arm, pose, speed, ...)`
- `safe_open_gripper(arm)`
- `safe_close_gripper(arm)`
- `perform_manual_alignment_flow(arm, object_name)`
- `get_stacked_place_position(place_count)`

These workflow helpers are available in `../../scripts/elephant/pickup_object.py`.

## Required Inputs

Ask for these before starting:

| Input | Description |
|---|---|
| Target object description | Natural language description such as `"blue cap vial"` |
| Object Z touch height | Final pickup Z in mm; default in the script is `155.0` |
| Robot IP | Elephant / Pi IP address; script uses `192.168.50.128` |
| Camera readiness | Confirm Pi camera and CAM2 streams are visible |
| YOLO model path | Use `blue_cap_vial.pt` if present, otherwise `yolo26s.pt` |

If VLM is used, `OPENROUTER_API_KEY` must be configured locally. Never ask the user to paste secrets into chat.

## Camera Streams

Use the installed `elephant_driver.combined_viewer` module to expose both cameras and their YOLO overlays. The Elephant edge service starts it automatically when `ELEPHANT_START_COMBINED_VIEWER=true`. The module intentionally uses the existing `elephant_driver` camera stack:

- Pi camera: `elephant_driver.camera.CameraConfig` and `start_pi_camera_stream_server`
- CAM2: `elephant_driver.cv.DEFAULT_STREAM_URL` and `capture_snapshot`

The Pi-hosted camera server uses `pi`, not `cam0`, in its own routes:

```text
Pi-hosted raw live:    http://<PI_IP>:5000/pi
Pi-hosted raw image:   http://<PI_IP>:5000/snapshot/pi
```

The local combined viewer then proxies that Pi stream into the routes below.

Default local URLs:

```text
Combined viewer:       http://127.0.0.1:5000
Pi camera raw live:    http://127.0.0.1:5000/pi_camera
Pi camera YOLO live:   http://127.0.0.1:5000/pi_camera_yolo
Pi camera raw image:   http://127.0.0.1:5000/snapshot/pi_camera
Pi camera YOLO image:  http://127.0.0.1:5000/snapshot/pi_camera_yolo
CAM2 raw live:         http://127.0.0.1:5000/cam2
CAM2 YOLO live:        http://127.0.0.1:5000/cam2_yolo
CAM2 raw image:        http://127.0.0.1:5000/snapshot/cam2
CAM2 YOLO image:       http://127.0.0.1:5000/snapshot/cam2_yolo
```

Start the viewer with:

```bash
python -m elephant_driver.combined_viewer --pi-ip 192.168.50.128 --start-pi-stream --pi-stream-port 5000 --workdir reports/elephant_camera --cam2-stream-url rtsp://100.125.227.14:8554/livestream --yolo-model-path elephant/yolov8n.pt
```

## Motion Limits (Mandatory)

These limits apply to **every** Elephant pickup workflow: Python scripts, PUDA protocol JSON, and ad-hoc `move` commands.

| Limit | Rule |
|---|---|
| Speed | `speed` on every `move` step must be **≤ 100**. Use `100` for scan, approach, descend, lift, place, and recovery. Never use `180`, `220`, or other higher values in pickup flows. |
| Rotation | Each pose rotation component (`rx`, `ry`, `rz`) must stay within **-180° to 180°** (inclusive). Normalize equivalent angles (for example `359.9` → `-0.1`) before generating or running a protocol. |

Before creating or running a pickup protocol, validate **every** `move` command:

1. `params.speed <= 100`
2. `params.coords[3]`, `[4]`, and `[5]` are each in `[-180, 180]`

Reusable helpers in `../../scripts/elephant/pickup_object.py`:

```python
from scripts.elephant.pickup_object import (
    MAX_PICKUP_SPEED,
    clamp_pickup_speed,
    normalize_rotation_deg,
    normalize_pose_rotations,
)

speed = clamp_pickup_speed(220)  # -> 100
coords = normalize_pose_rotations([-331.06, 296.51, 330.0, 179.99, 0.001, 111.0])
```

Example protocol `move` step (correct):

```json
{
  "name": "move",
  "machine_id": "elephant",
  "params": {
    "coords": [-331.06, 296.51, 330.0, 179.99, 0.001, 111.0],
    "speed": 100
  }
}
```

## Robot Constants

Use these calibrated defaults unless the workspace has been recalibrated:

```python
ROBOT_IP = "192.168.50.128"
ROBOT_PORT = 5001

SCAN_POSITION = [-250, 280.0, 330, -179.730594, -0.396744, 110.994829]
PLACE_POSITION = [-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]

DEFAULT_Z_TOUCH = 155.0
MAX_PICKUP_SPEED = 100
MOVE_SPEED = 100
PICK_SPEED = 100
DESCEND_SPEED = 100
LIFT_MM = 60.0

ROBOT_X_MIN, ROBOT_X_MAX = -500.0, -100.0
ROBOT_Y_MIN, ROBOT_Y_MAX = -250.0, 400.0
```

Pixel-to-robot affine mapping:

```python
AFFINE_X = [-0.00055275, 0.55156563, -465.44779855]
AFFINE_Y = [0.53339222, 0.02927655, 101.07712885]
```

Conversion:

```python
robot_x = AFFINE_X[0] * px + AFFINE_X[1] * py + AFFINE_X[2]
robot_y = AFFINE_Y[0] * px + AFFINE_Y[1] * py + AFFINE_Y[2]
```

Clamp the result to the robot workspace before moving.

The reusable helper is:

```python
from scripts.elephant.pickup_object import target_from_detection

pick_x, pick_y = target_from_detection(detection)
```

## Elephant Driver Usage

Basic connection pattern:

```python
from elephant_driver import CameraCalibration, CameraConfig, Elephant, Pose6D

with Elephant(ip=ROBOT_IP, port=5001, camera=CAMERA, calibration=CALIBRATION) as arm:
    arm.init_gripper()
    arm.open_gripper()
    arm.move(Pose6D.from_any(SCAN_POSITION), speed=MOVE_SPEED)
```

Important driver behavior:

- `Elephant.move(...)` sends absolute Cartesian poses.
- `Pose6D.from_any(...)` accepts a six-value list.
- `open_gripper()` and `close_gripper()` control the electric gripper.
- `init_gripper()` must be called once before open/close commands.
- The driver normalizes rotation by default to avoid long wrist flips near +/-180 degrees.

## Detection Workflow

1. Capture a fresh Pi camera image using the driver-backed combined viewer. The edge should have `ELEPHANT_START_PI_STREAM=true` so the Pi-hosted `/pi` stream is live.
2. Prefer the local Pi camera YOLO snapshot:

```text
http://127.0.0.1:5000/snapshot/pi_camera_yolo
```

3. Fall back to the raw Pi camera snapshot only if YOLO snapshot is unavailable.
4. Run YOLO to get candidate boxes.
5. Use VLM marker reasoning to choose the correct YOLO box.
6. If YOLO candidate selection fails, use strict direct VLM fallback.
7. Reject detections near the place position so already-placed objects are not picked again.
8. Save a debug image showing candidates, markers, selected target, and image center.

Priority if multiple target objects exist:

```text
1. Top row first
2. Within the same row, rightmost object first
```

## Pickup Workflow

For each target object:

1. Ensure the robot is at `SCAN_POSITION`.
2. Capture and detect the target object.
3. Convert detection center `(cx, cy)` to robot `(pick_x, pick_y)`.
4. Clamp `(pick_x, pick_y)` to workspace bounds.
5. Move above the target at scan Z.
6. Descend to `z_touch + 15 mm` for CAM2 alignment.
7. Run `perform_manual_alignment_flow(arm, object_name)` and require positive CAM2 alignment confirmation.
8. If alignment is confirmed, read the current refined XY from `arm.get_coords()`.
9. Only after confirmed CAM2 alignment, descend to `z_touch` while keeping the refined XY.
10. Close the electric gripper and wait for settle.
11. Lift straight up to scan Z.
12. Return to scan position.
13. Move above the place position.
14. Descend to place Z.
15. Open the gripper.
16. Raise straight up, then return to scan position before the next detection.

After CAM2 alignment is confirmed, the reusable motion helper is:

```python
from scripts.elephant.pickup_object import pick_after_alignment

result = pick_after_alignment(
    arm,
    pick_x=pick_x,
    pick_y=pick_y,
    z_touch=z_touch,
    place_count=pick_count,
    alignment_confirmed=True,
)
```

`pick_after_alignment(...)` raises an error unless `alignment_confirmed=True`. Do not catch or bypass that error in pickup flows.

## PUDA JSON Sequencing

PUDA JSON has no built-in interactive CAM2 confirmation command. For pickup work, do not generate or run a single JSON protocol that moves from scan height directly to `z_touch` and `close_gripper`.

Use this split sequence instead:

1. Detection/approach protocol: move above the target, then descend only to `z_touch + 15 mm`.
2. Run CAM2 YOLO alignment and human confirmation.
3. Only after alignment is confirmed, run the post-alignment pickup/place protocol that descends to `z_touch` and closes the gripper.

## Placement

The base place pose is:

```python
PLACE_POSITION = [-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]
```

`get_stacked_place_position(place_count)` offsets X by `-30 mm` for each placed object:

```python
pose[0] = PLACE_POSITION[0] - (30.0 * place_count)
```

Do not pick objects detected near the place position. Treat them as already placed.

## Safety Rules

- Enforce the [Motion Limits](#motion-limits-mandatory) on every pickup script and protocol before execution.
- Always move to scan Z before large XY moves.
- Always initialize and open the gripper before starting the pick loop.
- Never descend to `z_touch` until CAM2 alignment is confirmed.
- Never close the gripper for pickup unless CAM2 alignment has been confirmed in the current pick attempt.
- Keep small alignment moves in Y only unless recalibrating the camera/robot mapping.
- Preserve current rotation during local moves unless intentionally commanding a known pose.
- Always close the gripper before lifting.
- Always lift straight up to scan Z after pickup and after placement.
- Stop if object detection is not confident.
- Stop if CAM2 alignment cannot see both tape markers or the target.
- Do not ask the user to paste API keys or secrets into chat.

## Debug Outputs

The workflow can write these files:

```text
optimized.jpg
yolo_overlay.jpg
marker_debug.jpg
detection_debug.jpg
target_reference_crop.jpg
grip_verify.jpg
grip_verify_yolo_inner_tape_alignment_debug.jpg
initial_count_debug.jpg
```

Use these debug images before changing calibration, thresholds, or object prompts.
