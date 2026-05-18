---
name: elephant-alignment
description: Align the Elephant Pro630 gripper over a target object using Logitech CAM2 YOLO detections and the two inner tape-edge lines on the gripper.
---

# Elephant Alignment

Use this reference when the task is to align the Elephant Pro630 gripper before pickup. The alignment method uses the Logitech CAM2 side/front view. It does not use VLM for the alignment decision.

## Core Idea

The gripper has two visible tape markers. CAM2 YOLO detects the tape boxes and the target object. Alignment is correct when the target object's center x-coordinate is centered between the two inner vertical tape edges:

```text
left_inner_x  = right edge of left tape box
right_inner_x = left edge of right tape box
gap_center_x  = (left_inner_x + right_inner_x) / 2
offset_px     = object_center_x - gap_center_x
```

The gripper is aligned when `abs(offset_px) <= tolerance_px`.

## Related References

- Elephant driver: `elephant/driver/src/elephant_driver/elephant.py`
- Driver exports: `elephant/driver/src/elephant_driver/__init__.py`
- Driver README: `elephant/README.md`
- Alignment helper script: `../../scripts/elephant/alignment.py`
- Camera stream helper script: `../../scripts/elephant/camera_streams.py`
- Pickup workflow: `references/elephant/elephant-pickup-object.md`

## Required Hardware

- Elephant Robotics Pro630 connected on robot port `5001`
- Electric gripper with two visible tape markers
- Logitech C920e / CAM2 side-view camera
- YOLO model that can detect:
  - the target object class
  - the tape markers, with class names containing `tape`, `silver`, or `white_strip`

## Camera Stream Architecture

The Elephant workspace must use the existing camera support from `elephant_driver`:

- Pi camera capture uses `elephant_driver.camera.CameraConfig` and `capture_pi_image`.
- CAM2 capture uses the CV livestream URL and `capture_snapshot` from `elephant_driver.cv`.
- The local combined RAW + YOLO viewer is provided by `../../scripts/elephant/camera_streams.py`.

Important viewer endpoints:

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
python bears-skills/bears-workflows/scripts/elephant/camera_streams.py --pi-ip 192.168.50.128 --workdir reports/elephant_camera --yolo-model-path elephant/yolov8n.pt
```

## Configuration Values

Use these calibrated defaults unless the workspace has been recalibrated:

```python
INNER_LINE_TOLERANCE_MIN_PX = 5
INNER_LINE_TOLERANCE_RATIO = 0.12
INNER_LINE_TOLERANCE_MAX_PX = 8

INNER_TAPE_PAIR_MIN_GAP_PX = 2
INNER_TAPE_PAIR_MAX_GAP_PX = 180

CAM2_ALIGN_MIN_BOX_AREA = 150
CAM2_ALIGN_MAX_BOX_AREA_RATIO = 0.80

VERIFY_MM_PER_PIXEL = 0.35
VERIFY_Y_SIGN = 1
```

These defaults are also defined in `AlignmentConfig` in `../../scripts/elephant/alignment.py`.

## Alignment Workflow

1. Move the arm above the detected object at safe scan height.
2. Descend to alignment height, normally `z_touch + 15 mm`.
3. Capture CAM2 YOLO image from `http://127.0.0.1:5000/snapshot/cam2_yolo`.
4. Read CAM2 YOLO metadata from the live YOLO stream.
5. If metadata is not ready, run YOLO once on a raw CAM2 snapshot.
6. Filter detections by area and class.
7. Select target detections matching the current target class or object name.
8. Select tape detections whose class name includes `tape`, `silver`, or `white_strip`.
9. Test tape-pair candidates and choose the pair whose inner-edge center is closest to the target center.
10. Return a `GripCheck` result:
    - `picked_up=True` means aligned
    - `suggestion="left"` means move left
    - `suggestion="right"` means move right
    - `suggestion="none"` means no correction needed

The reusable geometry function is:

```python
from scripts.elephant.alignment import YoloCandidate, check_inner_tape_alignment

check = check_inner_tape_alignment(
    candidates,
    image_size=(width, height),
    target_name="blue cap vial",
)
```

## Manual Correction Loop

`perform_manual_alignment_flow(...)` is human-in-the-loop:

```text
y = confirm alignment and continue pickup
l = move robot Y by -2 mm times VERIFY_Y_SIGN
r = move robot Y by +2 mm times VERIFY_Y_SIGN
q = quit
```

After each correction, rerun `verify_gripper_alignment(...)`.

## Safety Rules

- Do not descend to the final pick Z until alignment is confirmed.
- Do not use VLM fallback for CAM2 alignment; this workflow is YOLO-only.
- Use the CAM2 YOLO debug image to inspect failures before changing thresholds.
- If YOLO cannot find two tape boxes, stop alignment and fix camera/model visibility.
- If YOLO cannot find the target class in CAM2, do not guess.
- Keep correction steps small; this workflow uses 2 mm manual shifts.
- Preserve current rotation during small alignment shifts unless intentionally recalibrating.

## Debug Outputs

The alignment workflow writes a debug image beside `grip_verify.jpg`:

```text
grip_verify_yolo_inner_tape_alignment_debug.jpg
```

The debug image shows:

- red boxes for tape candidates
- green box for the selected target
- red vertical lines for the two inner tape edges
- blue vertical line for the gap center
- green vertical line for object center
- offset and tolerance text
