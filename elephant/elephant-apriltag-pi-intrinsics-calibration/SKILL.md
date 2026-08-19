---
name: elephant-apriltag-pi-intrinsics-calibration
description: Calibrate Elephant Pi/top camera intrinsics from the 4×30 mm AprilTag 36h11 target using PUDA-controlled safe viewpoints and OpenCV.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [puda, elephant, camera-calibration, opencv, apriltag, intrinsics]
---

# Elephant AprilTag Pi Intrinsics Calibration

Use this skill when the user asks to calibrate or improve the **Elephant Pi/top camera intrinsics** using the existing four 30 mm AprilTag 36h11 target.

This is for **camera intrinsics only** (`camera_matrix`, `dist_coeffs`). Do not confuse it with full hand-eye calibration; hand-eye uses the intrinsics afterward.

## Known target geometry

The printed target uses AprilTag 36h11 IDs `0, 1, 2, 3`, each with black-square tag size `30 mm = 0.030 m`.

Measured physical gaps between black-square edges:

```text
gap_x = 200 mm
gap_y = 215 mm
```

Therefore origin spacing between neighboring black-square top-left corners is:

```text
x spacing = 30 + 200 = 230 mm = 0.230 m
y spacing = 30 + 215 = 245 mm = 0.245 m
```

Observed Pi image arrangement after moving up was:

```text
ID 2    ID 3

ID 1    ID 0
```

Target frame used for calibration:

```text
ID 2: (0.000, 0.000, 0.000)
ID 3: (0.230, 0.000, 0.000)
ID 1: (0.000, 0.245, 0.000)
ID 0: (0.230, 0.245, 0.000)
```

Important: OpenCV AprilTag corner ordering needed a 180° correction for every tag in this physical setup:

```json
"tag_corner_rotations": {
  "0": 2,
  "1": 2,
  "2": 2,
  "3": 2
}
```

This correction reduced reprojection fit from ~47 px RMS to ~1.95 px RMS.

## Files and paths

Primary config:

```text
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_config.json
```

Intrinsics output:

```text
/home/puda/elephant/calibration/pi_camera_intrinsics.json
```

Calibration report:

```text
/home/puda/elephant/calibration/pi_camera_intrinsics_report.json
```

Scripts created for this workflow:

```text
/home/puda/elephant/calibration/scripts/calibrate_pi_intrinsics_from_apriltags.py
/home/puda/elephant/calibration/scripts/collect_pi_intrinsics_views.py
/home/puda/elephant/calibration/scripts/collect_pi_intrinsics_tilt_views.py
/home/puda/elephant/calibration/scripts/detect_apriltag_target_pose.py
```

Capture directory:

```text
/home/puda/elephant/calibration/apriltag_intrinsics_capture/
```

Overlay directory:

```text
/home/puda/elephant/calibration/apriltag_30mm_overlays/
```

## Prerequisites

1. Load `puda-machine-control` first for PUDA command conventions and Elephant safety notes.
2. Confirm the robot state is idle:

```bash
cd /home/puda/puda-control
puda machine state elephant
```

3. Confirm the Pi/top camera stream is working. The combined viewer MJPEG route is usually:

```text
http://elephant:5003/pi
```

4. Confirm all 4 tags are visible and decodable from the Pi camera. A known good detection arrangement is:

```text
ID 2    ID 3
ID 1    ID 0
```

## Calibration workflow

### 1. Verify / update target config

Check `/home/puda/elephant/calibration/apriltag_30mm_hand_eye_config.json` includes:

```json
{
  "camera_name": "pi",
  "camera_stream_url": "http://elephant:5003/pi",
  "tag_family": "DICT_APRILTAG_36H11",
  "tag_ids": [0, 1, 2, 3],
  "tag_size_m": 0.03,
  "mode": "eye_in_hand",
  "tag_origins_m": {
    "0": [0.23, 0.245, 0.0],
    "1": [0.0, 0.245, 0.0],
    "2": [0.0, 0.0, 0.0],
    "3": [0.23, 0.0, 0.0]
  },
  "tag_corner_rotations": {
    "0": 2,
    "1": 2,
    "2": 2,
    "3": 2
  },
  "intrinsics_path": "/home/puda/elephant/calibration/pi_camera_intrinsics.json"
}
```

If the user reprints, remounts, or reorders the tags, redetect arrangement and update `tag_origins_m` and `tag_corner_rotations` before calibrating.

### 2. Capture calibration views

Preferred: collect **manual board tilt views** while keeping all 4 tags visible. Tell the user to vary:

- target position in image: center, left, right, top, bottom,
- scale/distance: near and far,
- tilt/rotation: pitch/roll/yaw of the board,
- lighting: avoid glare and blur.

Need **8–15 usable views minimum**. More is better.

If the user authorizes robot motion, use safe high-Z viewpoints and conservative speed. Existing collector:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/collect_pi_intrinsics_views.py
```

This script previously collected safe translational viewpoints around:

```text
[-220, 280, 380]
[-280, 280, 380]
[-250, 250, 380]
[-250, 310, 380]
[-220, 310, 390]
[-280, 250, 390]
```

Caution: pure translation views are weak for intrinsics. Wrist tilt views may clip tags; inspect overlays before accepting.

### 3. Run calibration

Run:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/calibrate_pi_intrinsics_from_apriltags.py \
  --config calibration/apriltag_30mm_hand_eye_config.json \
  --images 'calibration/apriltag_30mm_images/*pi*jpg' 'calibration/apriltag_intrinsics_capture/*jpg' \
  --output calibration/pi_camera_intrinsics.json \
  --report calibration/pi_camera_intrinsics_report.json \
  --min-tags 4 \
  --min-views 8
```

The script:

- detects AprilTag 36h11 IDs `0..3`,
- requires all 4 tags per accepted view by default,
- applies `tag_corner_rotations`,
- calls `cv2.calibrateCamera`,
- writes `pi_camera_intrinsics.json` and `pi_camera_intrinsics_report.json`.

### 4. Interpret results

Quality targets:

```text
ideal RMS reprojection error:      < 1.0 px
acceptable RMS for provisional use: < 1.5 px
provisional / weak:                1.5–2.0 px
not acceptable:                    > 2.0 px or implausible distortion
```

Previous provisional result from 8 usable robot-collected translation views:

```text
RMS: 1.95 px
quality: provisional
fx = 646.639
fy = 661.640
cx = 340.708
cy = 154.387
k1 = 1.146807
k2 = -3.302082
p1 = -0.134208
p2 = -0.025342
k3 = 5.217722
```

Treat this as **not good enough for final high-confidence hand-eye calibration**. Use it only for pilot experiments unless improved.

## Critical pitfalls

- **Do not calibrate from repeated identical frames.** They do not add meaningful constraints.
- **Do not accept a solve only because there are 8 views.** Check RMS and distortion plausibility.
- **Do not use the wrong tag corner order.** In this setup, all tags required `tag_corner_rotations=2`.
- **Do not combine clipped or 2/3-tag views** when the script is configured for full target intrinsics; rejected views should stay rejected.
- **Do not claim final intrinsics if RMS is provisional.** Say explicitly that calibration is provisional and ask for more varied manual board tilt views.
- **Avoid large robot wrist tilt moves unless user authorizes and physical clearance is obvious.** Previous `rx` tilt attempts clipped tags; `ry/rz` small tilts kept all tags visible but worsened the combined solve.

## Verification checklist

Before reporting success:

1. Confirm `puda machine state elephant` is idle.
2. Confirm the output JSON exists and loads:

```bash
python3 -m json.tool /home/puda/elephant/calibration/pi_camera_intrinsics.json >/dev/null
python3 -m json.tool /home/puda/elephant/calibration/pi_camera_intrinsics_report.json >/dev/null
```

3. Report:

- number of accepted views,
- image size,
- RMS reprojection error,
- quality label,
- camera matrix,
- distortion coefficients,
- whether intrinsics are final or provisional.

4. Include representative `MEDIA:` images/overlays if useful.

## Next step after acceptable intrinsics

Once RMS is acceptable, use `/home/puda/elephant/calibration/pi_camera_intrinsics.json` with the AprilTag PnP detector and proceed to full eye-in-hand calibration sample collection.