---
name: elephant-blue-vial-yolo-pick-place
description: Safely capture, detect, align, pick, relocate, and place a blue-cap glass vial with Elephant using Pi/top plus physical front/side YOLO and auditable PUDA protocols.
version: 1.0.5
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [puda, elephant, robot, blue-vial, yolo, pick-place, camera-guidance]
---

# Elephant Blue-Vial YOLO Pick and Place

Use this skill when the user asks Elephant to capture images, detect a **blue-cap glass vial**, move above it, align the gripper with camera YOLO, pick it, move to scan, or place it at an absolute/relative target.

Load `puda-machine-control` first. Operate Elephant through the **PUDA CLI and protocol JSON files**, not direct robot Python calls.

## Fixed environment

```text
PUDA project:       /home/puda/puda-control
Elephant project:   /home/puda/elephant
Machine ID:         elephant
Protocol directory: /home/puda/puda-control/protocols
Capture directory:  /home/puda/elephant_captures
YOLO model:         /home/puda/elephant/blue_vial_3cam_yolo26s_new_best_v2.pt
Scan pose:          [-250, 280, 330, -179.99, 0, 111]
Default place pose: [-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]
Alignment height:   Z=170 mm
Pickup/place height: Z=155 mm
Normal explicit speed: 100
```

Explicit protocol speed overrides the driver's default speed. Use `speed: 100` for this workflow unless the user requests otherwise.

## Camera roles

Use fresh direct MediaMTX HLS frames for front/side alignment, not the combined viewer on `:5003`.

```text
Physical front/two-tape view:
http://elephant:8888/elephant-side/index.m3u8

Physical side/"gripper side" view:
http://elephant:8888/elephant-front/index.m3u8
```

The HLS route names are opposite the physical alignment roles. Assign roles by detections:

- physical front: vial plus two `tape` detections,
- physical side: vial plus one `gripper side` detection.

Pi/top capture routes:

```text
http://192.168.1.159:5000/snapshot/cam0
http://192.168.1.159:5000/cam0
```

Preferred detector command:

```bash
cd /home/puda/elephant
uv run python scripts/capture_detect_blue_vial.py
```

It should preserve the raw image, YOLO overlay, detection JSON, selected cap box, blue connected component, and detector agreement.

## Safety invariants

1. Check `puda machine state elephant` before motion. Proceed only from `idle` with no active run.
2. Wait about 5 seconds after robot motion reaches idle before trusting camera frames.
3. Move laterally only at a clearance height, normally `Z=330 mm`.
4. Descend vertically at fixed verified XY.
5. Never close the gripper unless both front and side alignment gates pass on fresh frames.
6. After closing, lift vertically to clearance before lateral travel.
7. For placement, descend vertically, open at the requested absolute Z, and lift vertically clear.
8. Stop if a correction fails, changes the wrong sign, or does not improve the measured error. Do not repeat speculative motion.
9. Do not use an ambiguous image target or an unverified affine conversion for final descent.
10. Do not resend a close/open/final motion after PUDA already reported success; verify state and pose instead.
11. For front/side YOLO alignment, move only to `Z=170 mm`. Do **not** descend to the `Z=155 mm` pickup position before both YOLO alignment gates pass.

## Phase 1 — move to scan, capture, and detect

The Pi/top affine mapping is calibrated for the scan pose. Therefore **the robot must be at scan position before Pi image capture and vial detection**.

1. Verify idle and read the current pose:

```bash
cd /home/puda/puda-control
puda machine state elephant
# Use the established get-position PUDA protocol or direct read-only getter.
```

2. Compare the actual pose with the scan pose:

```text
[-250, 280, 330, -179.99, 0, 111]
```

Treat the robot as already at scan when Cartesian position is within `±2 mm` per axis and orientation is within `±2°` per axis. If it is outside tolerance, run the Elephant `scan` command with explicit `speed: 100`, then verify the resulting pose and idle state. Wait about 5 seconds after reaching scan so the Pi frame is fresh and stable.

Do not capture or convert Pi vial pixels before this scan-pose gate passes.

3. Capture Pi/top and detect the vial:

```bash
cd /home/puda/elephant
uv run python scripts/capture_detect_blue_vial.py
```

4. Require exactly one unambiguous `blue cap vial` candidate. Cross-check YOLO against the blue connected component. Reject or ask for clarification when:

- multiple plausible vials exist,
- the blue component is tiny or unrelated,
- YOLO and blue centers disagree materially,
- the cap/object is occluded,
- image rotation/crop differs from calibration.

5. Preserve and attach the overlay as evidence.

## Phase 2 — Pi pixel to robot XY and high hover

Operational 640×480 Pi/top affine mapping:

```text
X = -0.00055275*px + 0.55156563*py - 465.44779855
Y =  0.53339222*px + 0.02927655*py + 101.07712885
```

Calculate with a tool, never mentally. Treat the affine result as a high-hover candidate, not proof of pickup alignment.

Move first to:

```text
[X_target, Y_target, 330, -179.99, 0, 111]
```

Use a small auditable PUDA protocol. Verify command success, machine idle, and actual position before descending.

If camera rotation, crop, scan pose, or the combined viewer configuration changed, validate the mapping against a known point before using it.

## Phase 3 — descend to alignment height

From the high hover, descend vertically only to the dedicated YOLO alignment height:

```text
[X_target, Y_target, 170, -179.99, 0, 111]
```

This `Z=170 mm` move is the alignment move; it replaces any premature descent to the pickup position. Hold at `Z=170` while making all bounded XY corrections and recapturing YOLO evidence. Do **not** move to `Z=155 mm` yet.

After PUDA reports success:

1. verify machine idle,
2. wait about 5 seconds,
3. capture fresh direct HLS frames from both physical views,
4. run YOLO with the trained model.

Example direct HLS capture:

```bash
ffmpeg -loglevel error -y \
  -i http://elephant:8888/elephant-side/index.m3u8 \
  -frames:v 1 front.jpg

ffmpeg -loglevel error -y \
  -i http://elephant:8888/elephant-front/index.m3u8 \
  -frames:v 1 side.jpg
```

## Phase 4 — front and side YOLO alignment

### Front/two-tape gate

Require:

- one `blue cap vial`,
- two `tape` detections.

Sort tape boxes left-to-right. Define the center of the gripper gap from the inner tape edges:

```text
gripper_center_x = (left_tape.x2 + right_tape.x1) / 2
front_offset_px = vial.cx - gripper_center_x
front_tolerance_px = max(5, min(8, int(gap_width * 0.12)))
```

Pass when:

```text
abs(front_offset_px) <= front_tolerance_px
```

A known bounded correction model is:

```text
dy_mm = front_offset_px * 0.35
```

Apply only a small correction, normally clamped to about `±7 mm`, at alignment Z. Recapture both views after every correction. If the offset does not improve, stop rather than repeating it.

### Side/straightness gate

Require:

- one `blue cap vial`,
- one `gripper side` detection.

The side camera has calibrated perspective distortion. Do **not** require the raw vial and gripper centers to be equal near the image edges. Compute:

```text
raw_offset_px = vial.cx - gripper_side.cx
nx = clamp((gripper_side.cx - image_width/2) / (image_width/2), -1, 1)
expected_perspective_offset_px = -40.0 * nx
side_offset_px = raw_offset_px - expected_perspective_offset_px
side_tolerance_px = clamp(int(gripper_width_px * 0.18), 8, 24)
pass when abs(side_offset_px) <= side_tolerance_px
```

Do not apply the old open-loop `dx_mm = -side_offset_px * 0.35` rule or jump directly by `8 mm`; its sign was observed to be wrong at some workspace locations and it can pass through visual alignment before settling farther away.

Use a closed-loop sign-calibration procedure at `Z=170`:

1. Make at most a `2 mm` X probe.
2. Wait for the robot to finish and settle, then obtain a genuinely fresh frame.
3. Compare the new **perspective-corrected** error with the pre-probe error.
4. Keep that sign only when the absolute error decreases; otherwise immediately revert the probe.
5. Continue only in `1–2 mm` increments, recapturing after every settled move, and stop as soon as the side gate passes.

Do not infer success from a transient view while the robot is still moving or from a buffered HLS frame. If the gripper appears aligned during motion but the settled error is larger, treat that as overshoot/latency, revert, and recalibrate with smaller steps.

### Alignment gate

Proceed only when **both** front and side pass on the same fresh capture set. Save an annotated montage and JSON containing boxes, centers, offsets, tolerances, and pass/fail results.

## Phase 5 — pick

Use a decomposed sequence so final descent success is known before gripper closure.

### A. Final vertical descent

Only after both front and side YOLO gates pass on the same fresh capture set, preserve the actual aligned XY/orientation and perform the final vertical descent to absolute:

```text
Z=155 mm
```

Verify PUDA success before continuing.

### B. Close, lift, scan

Run:

1. `close_gripper`,
2. vertical lift at the same XY to `Z=330 mm`,
3. `scan` with explicit `speed: 100`.

The normal scan result is approximately:

```text
[-250, 280, 330, -179.99, 0, 111]
```

Verify final position and idle state. Capture fresh front/side frames; no vial at the source supports successful pickup. If the held vial is outside the frame, say so rather than claiming direct visual confirmation of the grip.

## Phase 6 — place

### Absolute placement

If the user asks to place the vial but does not provide a place position, use this default absolute place pose without asking for clarification:

```text
[-264.0, 175.0, 140.0, 179.99, 0.0, 113.0]
```

An explicitly supplied absolute or relative place position always overrides this default.

1. Resolve the placement target from the user's explicit request, or use the default pose above when omitted. Travel laterally at `Z=330 mm` to the resolved placement XY and orientation.
2. Read back the achieved pose.
3. If the requested Z is below the proven `Z=155 mm` release height, first descend only to `Z=155`, capture fresh front/side evidence, and inspect table/vial clearance.
4. Descend below `Z=155` only when the images clearly show enough clearance for the full remaining distance. If the vial is already touching or extremely close to the table, do not descend farther; release at the safe staged height and explicitly report the Z deviation.
5. `open_gripper` to place the vial.
6. Lift vertically at the same XY to `Z=330 mm`.
7. Move to scan only if requested.

### Relative placement

For a request such as `dx=40, dy=-40, z=155`:

1. While holding the vial at clearance height, run `move_relative` with:

```json
{"dx": 40, "dy": -40, "dz": 0, "speed": 100}
```

2. Read the achieved pose; do not assume exact commanded XY.
3. Descend at the achieved XY to absolute `Z=155`.
4. Open the gripper.
5. Lift vertically to `Z=330`.

Interpret bare `z=155` in a placement request as an **absolute placement height** unless the user explicitly says `dz=155`.

## Minimal PUDA protocol structure

```json
{
  "project_id": "45cae461-ec2b-4cc4-9b92-445f9d20ef20",
  "protocol_id": "unique-descriptive-id",
  "user_id": "858da198-3be0-41d7-9cc5-3b2e9ce80d6e",
  "username": "elephant",
  "description": "Describe the bounded physical action.",
  "commands": [
    {
      "step_number": 1,
      "name": "move",
      "machine_id": "elephant",
      "params": {
        "coords": [-250, 280, 330, -179.99, 0, 111],
        "speed": 100
      }
    }
  ]
}
```

Run it from:

```bash
cd /home/puda/puda-control
puda protocol run -f protocols/<file>.json
```

## Verification checklist

Before reporting completion:

- [ ] Robot pose checked before Pi capture
- [ ] Robot moved to scan if outside scan-pose tolerance
- [ ] Scan pose and idle state verified; camera allowed to settle
- [ ] Initial Pi/top raw image, overlay, and detection JSON saved
- [ ] Exactly one unambiguous vial detected
- [ ] High hover completed and actual pose checked
- [ ] Robot moved to `Z=170 mm` for YOLO alignment, without first descending to pickup height
- [ ] Fresh direct HLS front and side images captured
- [ ] Front gate passed
- [ ] Side gate passed
- [ ] After both YOLO gates passed, final descent to Z=155 succeeded
- [ ] Gripper close/open command succeeded as appropriate
- [ ] Vertical lift to clearance succeeded
- [ ] Final machine state is idle
- [ ] Final pose read back
- [ ] Post-action camera verification captured
- [ ] Run IDs, offsets, confidence, position, and uncertainty reported

## Failure handling

- If START or queued commands return `RUN_ID_MISMATCH`, ensure a START succeeds and wait about 5 seconds before queued commands.
- If a run remains sticky despite `idle`, clear the stale run per `puda-machine-control` before retrying.
- If a motion times out, inspect actual pose and finish only the residual; never replay the full move blindly.
- If direct HLS and combined viewer disagree, trust fresh direct HLS for physical front/side alignment and document the route mapping.
- If any detector reference disappears at alignment height, lift or hold safely and recapture; do not descend to pickup.
