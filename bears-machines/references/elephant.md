---
name: elephant-machine
description: Generate commands for the Elephant Pro630 robot arm, including Cartesian/joint motion, scan/reset flows, electric gripper control, Pi-camera capture, livestream snapshot capture, and camera calibration.
---

# Elephant Machine Skills

Generate commands for the Elephant Pro630 6-axis robot arm.

## Purpose

This skill enables generation of commands for the Elephant machine in PUDA workflows. These commands automate robot-arm motion, scan positioning, gripper actions, recovery/reset flows, Pi-camera capture, livestream snapshot capture, and camera-assisted vision steps.

## When to Use

Load this skill when:
- Users describe tasks to be executed on the Elephant robot arm
- Converting manual pick-and-place or manipulation procedures into automated PUDA protocols
- Processing natural language requests for robot movement, positioning, gripper actions, or recovery flows
- Working with workflows that require Pi-camera or livestream image capture from the Elephant setup

## Required Resources

**IMPORTANT**: Before generating any commands, **always consult these resources**:

1. **Consult CLI**: Run `puda machine commands elephant` to review available commands and parameters

**Do not generate commands without first consulting these resources** to ensure accuracy and compatibility.

## Command Structure

Each Elephant command follows the standard protocol command structure (see protocol-generator reference). Key Elephant-specific details:

- `machine_id`: Must be `"elephant"` (string)

## Rules and Restrictions

The following rules **must** be strictly followed when generating Elephant commands:

### Handling Missing Information

- If required information is missing, **do not assume or guess** values. Ask the user for the missing pose, speed, offsets, or grasp details before finalizing commands.
- If a Cartesian target is needed, provide all 6 pose values: `x`, `y`, `z`, `rx`, `ry`, `rz`.

### Motion and Pose Constraints

- Cartesian motion uses 6D poses in the form `[x, y, z, rx, ry, rz]`.
- Valid coordinate ranges are:
  - `x`: -630 to 630 mm
  - `y`: -630 to 630 mm
  - `z`: -425 to 835 mm
  - `rx`, `ry`, `rz`: -180 to 180 deg
- Speed must be between `1` and `3000`.
- Prefer `move(...)` for blocking moves that should wait for completion.
- Prefer `send_coords(...)` or `send_angles(...)` only when a non-blocking low-level command is actually desired.

### Scan and Recovery

- Use `scan()` to move the robot to its configured scan pose before camera capture or after recovery flows.
- `reset()` already clears errors, restarts the robot, and moves to the configured scan position.

### Gripper Rules

- The current driver targets the **electric gripper** by default.
- Use `init_gripper()` once after a power cycle before relying on `open_gripper()` or `close_gripper()`.
- Sequence gripper actions logically around motion:
  - open before approach if preparing to pick
  - close to grasp
  - open to release
- `set_gripper_value()` is for the adaptive gripper path and should not be the default recommendation unless the user explicitly indicates that hardware configuration.

### Camera Rules

- Use `capture_image()` or `capture_stream_image()` when the workflow requires visual confirmation or CV input.
- Use `capture_stream_image()` for livestream snapshot capture.
- If image-based offset correction is needed, use `pixel_to_robot_offset(...)` with a known `z_touch` and a calibrated camera setup.

### Command Dependencies and Sequencing

**Important**: If the user's request contains invalid commands, incorrect sequencing, or violates driver constraints, **do not blindly follow the request**. Explain the issue and correct the command sequence.

**Critical sequencing rules:**
1. Ensure the robot is connected and powered before motion commands.
2. Before electric-gripper open/close operations after a power cycle, call `init_gripper()`.
3. Before camera-guided work, prefer moving to `scan()` first unless the workflow requires capture from another known-safe pose.
4. If a workflow ends in an uncertain or faulted state, prefer `reset()` or `scan()` rather than leaving the arm at an arbitrary pose.

## Instructions

1. **Consult Resources**: Consult the resources listed in the "Required Resources" section above before generating any commands.
2. **Verify sequencing and constraints**: Ensure motion, power, gripper, and camera steps are ordered safely and coherently for the requested workflow.
3. **Generate command**: Create command objects with `machine_id: "elephant"`, the appropriate command `name`, and valid `params`.
