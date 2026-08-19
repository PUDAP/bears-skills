---
name: elephant-apriltag-3d-hand-eye-calibration
description: Run provisional or final 3D OpenCV eye-in-hand calibration for Elephant Pi/top camera using the four 30 mm AprilTag 36h11 target and PUDA robot poses.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [puda, elephant, hand-eye-calibration, opencv, apriltag, eye-in-hand, robotics]
---

# Elephant AprilTag 3D OpenCV Hand-Eye Calibration

Use this skill when the user asks to run, improve, audit, or repeat the **3D OpenCV hand-eye calibration** for the Elephant robot Pi/top camera using the four 30 mm AprilTag target.

This skill is for **eye-in-hand hand-eye calibration** after Pi camera intrinsics exist. For intrinsics calibration itself, first load/use `elephant-apriltag-pi-intrinsics-calibration`.

## Physical target geometry

Target: four AprilTag 36h11 tags, IDs `0, 1, 2, 3`.

Measured tag/board geometry:

```text
tag black-square side = 30 mm = 0.030 m
gap_x between black-square edges = 200 mm
gap_y between black-square edges = 215 mm
x spacing between tag origins = 230 mm = 0.230 m
y spacing between tag origins = 245 mm = 0.245 m
```

Observed arrangement in the Pi/top image:

```text
ID 2    ID 3
ID 1    ID 0
```

Target frame assignment:

```text
ID 2: (0.000, 0.000, 0.000)
ID 3: (0.230, 0.000, 0.000)
ID 1: (0.000, 0.245, 0.000)
ID 0: (0.230, 0.245, 0.000)
```

The current target config requires 180° corner rotation for all tag correspondences:

```json
"tag_corner_rotations": {
  "0": 2,
  "1": 2,
  "2": 2,
  "3": 2
}
```

This is critical. Without it, reprojection errors were about `47 px`; with it, the intrinsic fit improved to about `1.95 px`.

## Key files

Main config:

```text
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_config.json
```

Pi intrinsics:

```text
/home/puda/elephant/calibration/pi_camera_intrinsics.json
```

Detector / PnP script:

```text
/home/puda/elephant/calibration/scripts/detect_apriltag_target_pose.py
```

Capture sample script:

```text
/home/puda/elephant/calibration/scripts/capture_apriltag_hand_eye_sample.py
```

OpenCV hand-eye solve script:

```text
/home/puda/elephant/calibration/scripts/solve_apriltag_hand_eye.py
```

Automated synchronized collector (primary, supplemental, and wide-rotation pose sets; supports append mode):

```text
/home/puda/elephant/calibration/scripts/collect_synchronized_hand_eye_samples.py
```

Robust subset and cross-dataset profile evaluation helpers:

```text
/home/puda/elephant/calibration/scripts/analyze_hand_eye_recal_subsets.py
/home/puda/elephant/calibration/scripts/evaluate_profiles_on_recal_dataset.py
```

Canonical profile path:

```text
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_profile.json
```

Provisional dataset builder from intrinsic-calibration views:

```text
/home/puda/elephant/calibration/scripts/build_hand_eye_dataset_from_intrinsics_views.py
```

Provisional artifacts from previous pilot run:

```text
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_samples_from_intrinsics.tsv
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_samples_from_intrinsics_metadata.jsonl
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_profile_from_intrinsics.json
/home/puda/elephant/calibration/apriltag_30mm_overlays/hand_eye_from_intrinsics/
```

## Prerequisites

1. Load `puda-machine-control` and follow PUDA safety conventions.
2. Confirm robot state is idle:

```bash
cd /home/puda/puda-control
puda machine state elephant
```

3. Confirm Pi camera stream works:

```text
http://elephant:5003/pi
```

4. Confirm all tags are visible/detectable from Pi image.
5. Confirm intrinsics file exists and is acceptable enough for the intended calibration:

```bash
python3 -m json.tool /home/puda/elephant/calibration/pi_camera_intrinsics.json >/dev/null
```

Known provisional intrinsics from prior run:

```text
quality = provisional
RMS = 1.95 px
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

For final calibration, improve intrinsics first if possible. RMS `< 1.0 px` is ideal, `< 1.5 px` is acceptable, `1.5–2.0 px` is provisional.

## Preferred final workflow

### 1. Collect synchronized hand-eye samples

Use synchronized image + actual robot pose at each view. Do **not** rely on commanded poses for final calibration.

Preferred command:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/capture_apriltag_hand_eye_sample.py \
  --config calibration/apriltag_30mm_hand_eye_config.json \
  --intrinsics calibration/pi_camera_intrinsics.json \
  --accept
```

The script should:

1. Capture one Pi image from `http://elephant:5003/pi`.
2. Immediately run PUDA `get_position` through `/home/puda/puda-control/protocols/get-elephant-position.json`.
3. Detect AprilTags and run `cv2.solvePnP`.
4. Append a solver-compatible TSV row:

```text
x<TAB>y<TAB>z<TAB>rx<TAB>ry<TAB>rz<TAB>X Y Z qw qx qy qz
```

5. Save sidecar metadata JSONL and overlay image.

### 2. Pose requirements

Collect at least **15 valid samples**, ideally **20–25**.

Include diverse, informative motion:

- X/Y translations across workspace.
- Z/depth changes.
- Safe wrist rotations around multiple axes.
- Board appears at different image locations and scales.
- Capture only after robot is idle.

Avoid:

- repeated identical frames,
- pure translation-only datasets,
- clipped tags,
- motion blur,
- using commanded pose instead of `get_position`,
- large unsupervised wrist tilts that may clip tags or collide.

### 3. Solve hand-eye calibration

Run:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/solve_apriltag_hand_eye.py \
  --config calibration/apriltag_30mm_hand_eye_config.json \
  --dataset calibration/apriltag_30mm_hand_eye_samples.tsv \
  --output calibration/apriltag_30mm_hand_eye_profile.json \
  --euler-order xyz
```

The solve script uses OpenCV `cv2.calibrateHandEye` with eye-in-hand convention:

```text
R_gripper2base, t_gripper2base = Elephant TCP/gripper pose
R_target2cam,   t_target2cam   = AprilTag PnP target pose in camera frame
output = R_cam2gripper, t_cam2gripper
```

The profile output transform is named:

```text
T_camera_gripper
```

Translations are in **millimetres**.

### 4. Evaluate solvers

Compare methods:

```text
TSAI
PARK
HORAUD
ANDREFF
DANIILIDIS
```

Prefer methods that are:

- numerically successful,
- physically plausible translation magnitude,
- low residual mean/max,
- similar to other plausible solvers,
- not degenerate identity / zero translation.

A previous provisional run selected **ANDREFF** as best by residual.

## Provisional run from intrinsic-calibration views

A prior pilot run used images and robot poses collected during Pi intrinsics calibration, then built a provisional dataset with:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/build_hand_eye_dataset_from_intrinsics_views.py
```

It produced:

```text
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_samples_from_intrinsics.tsv
/home/puda/elephant/calibration/apriltag_30mm_hand_eye_samples_from_intrinsics_metadata.jsonl
```

Then it solved:

```bash
cd /home/puda/elephant
uv run python calibration/scripts/solve_apriltag_hand_eye.py \
  --config calibration/apriltag_30mm_hand_eye_config.json \
  --dataset calibration/apriltag_30mm_hand_eye_samples_from_intrinsics.tsv \
  --output calibration/apriltag_30mm_hand_eye_profile_from_intrinsics.json \
  --euler-order xyz
```

Pilot result:

```text
profile: /home/puda/elephant/calibration/apriltag_30mm_hand_eye_profile_from_intrinsics.json
sample_count: 12
intrinsics quality: provisional, RMS 1.95 px
best method: ANDREFF
transform: T_camera_gripper
translation norm: 77.28 mm
mean residual: 11.08 mm
max residual: 19.16 mm
mean rotation residual: 2.30 deg
max rotation residual: 4.19 deg
rotation determinant: ~1.0
orthogonality error: ~5.58e-16
```

Pilot transform matrix, units mm:

```text
[[-0.8899227,  0.4525682, -0.0567414,   6.2923],
 [-0.4561094, -0.8826480,  0.1135636, -65.9718],
 [ 0.0013125,  0.1269431,  0.9919091, -39.7534],
 [ 0.0000000,  0.0000000,  0.0000000,   1.0000]]
```

Solver comparison from pilot run:

```text
TSAI:      mean 62.66 mm, max 150.05 mm, translation 0.00 mm; failed/uninformative motion warning
PARK:      mean 14.62 mm, max 22.30 mm, translation 175.70 mm
HORAUD:    mean 14.63 mm, max 22.30 mm, translation 175.70 mm
ANDREFF:   mean 11.08 mm, max 19.16 mm, translation 77.28 mm; selected
DANIILIDIS: mean 30.00 mm, max 122.96 mm, translation 989.00 mm; implausible
```

Treat this result as **rough pilot only**, not final production calibration.

## Quality thresholds

For final hand-eye calibration:

```text
excellent mean residual: < 3 mm
good/usable:             3–7 mm
provisional:             7–15 mm
poor:                    > 15 mm or unstable solvers
```

The pilot run mean residual `11.08 mm` is provisional.

## Critical pitfalls

- The combined viewer currently runs with `--no-pi-rotate-180`; capture and calibrate in the native Pi orientation. Do not reapply the retired 180° pixel correction unless the viewer rotation setting changes.
- Archive the prior synchronized TSV, metadata JSONL, and profile before a collector run that replaces output. Use the collector's `--append` mode for supplemental poses.
- A profile that had low residuals on an old dataset can be invalid after camera orientation, mount, stream, or intrinsics changes. Evaluate old and new profiles on the newly synchronized dataset before promoting either one.
- Do not select an outlier-filtered profile only by its training residual. Rank candidate subsets on all accepted samples, preserve the full dataset, and record excluded pose indices.
- Wide wrist rotations may improve OpenCV motion conditioning but often clip this large target. Accept only views with at least three tags and good PnP, and return Elephant to scan pose after collection.
- Do not claim a final calibration when using provisional intrinsics or commanded poses.
- Do not use the intrinsic-calibration views as a substitute for a proper synchronized hand-eye dataset unless the user explicitly asks for a pilot run.
- Do not ignore OpenCV warnings such as “not enough informative motions — include larger rotations”.
- Do not accept TSAI identity/zero-translation result as valid.
- DANIILIDIS can produce implausible huge translations; reject if physically inconsistent.
- Verify tag corner rotation correction (`tag_corner_rotations`) is included before PnP.
- Verify profile rotation determinant is close to `+1` and orthogonality error is near zero.
- Keep Elephant motion supervised and conservative; avoid large wrist rotations without operator awareness.

## Verification checklist

Before reporting results:

1. Validate output JSON:

```bash
python3 -m json.tool /home/puda/elephant/calibration/apriltag_30mm_hand_eye_profile.json >/dev/null
```

or for pilot profile:

```bash
python3 -m json.tool /home/puda/elephant/calibration/apriltag_30mm_hand_eye_profile_from_intrinsics.json >/dev/null
```

2. Check profile metrics with Python/NumPy under `uv run python` because system `python3` may not have NumPy:

```bash
cd /home/puda/elephant
uv run python - <<'PY'
import json, numpy as np
p='calibration/apriltag_30mm_hand_eye_profile_from_intrinsics.json'
d=json.load(open(p))
M=np.array(d['matrix'], float)
R=M[:3,:3]
print('method', d['method'])
print('sample_count', d['sample_count'])
print('residual_mean_mm', d['residual_mean_mm'])
print('residual_max_mm', d['residual_max_mm'])
print('translation_norm_mm', d['translation_norm_mm'])
print('det_R', np.linalg.det(R))
print('orthogonality_error', np.linalg.norm(R.T @ R - np.eye(3)))
PY
```

3. Verify robot state:

```bash
cd /home/puda/puda-control
puda machine state elephant
```

4. Report:

- dataset path,
- profile path,
- sample count,
- intrinsics quality,
- selected method,
- residuals,
- transform matrix,
- whether result is final or provisional,
- concrete next step to improve.

## Next step to improve from pilot to final

1. Improve Pi intrinsics with more manual board tilt views if possible.
2. Collect 20–25 synchronized hand-eye samples with `capture_apriltag_hand_eye_sample.py --accept`.
3. Include more safe wrist rotations while keeping all tags visible.
4. Solve again and require lower residuals before using for precise image-guided picking.
