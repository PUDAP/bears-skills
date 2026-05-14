---
name: elephant-machine
description: Generate commands for the Elephant Pro630 robot arm, including Cartesian/joint motion, scan/reset flows, electric gripper control, Pi-camera capture, and power control.
---

# Elephant Machine Skills

Generate commands for the Elephant Pro630 6-axis robot arm.

## Purpose

This skill enables generation of commands for the Elephant machine in PUDA workflows. These commands automate robot-arm motion, scan positioning, gripper actions, recovery/reset flows, power control, and Pi-camera-assisted vision steps.

## When to Use

Load this skill when:
- Users describe tasks to be executed on the Elephant robot arm
- Converting manual pick-and-place or manipulation procedures into automated PUDA protocols
- Processing natural language requests for robot movement, positioning, gripper actions, or recovery flows
- Working with workflows that require Pi-camera image capture from the Elephant setup

## Required Resources

**IMPORTANT**: Before generating any commands, **always consult these resources**:

1. **Consult CLI**: Run `puda machine commands elephant` to review available commands and parameters
2. **Driver Reference**: Ensure command intent matches the current Elephant driver behavior for motion, gripper, camera, and power operations

**Do not generate commands without first consulting these resources** to ensure accuracy and compatibility.

## Command Structure

Each Elephant command follows the standard protocol command structure. Key Elephant-specific details:

- `machine_id`: Must be `"elephant"` (string)

## Current Driver Capabilities

The current Elephant driver supports these public operations:

- Connection and recovery: `startup`, `disconnect`, `reconnect`
- Power: `power_on`, `power_off`, `is_power_on`
- Status: `is_moving`, `get_error`, `clear_error`, `get_robot_status`, `get_position`, `get_angles`, `get_coords`, `get_pose`
- Motion: `send_angles`, `send_coords`, `send_coord`, `send_angle`, `stop`, `wait_done`, `move`, `move_relative`, `scan`
- Gripper: `open_gripper`, `close_gripper`, `set_gripper_value`, `init_gripper`, `release_gripper`
- Recovery and safety: `reset`, `release_all_servos`, `focus_all_servos`
- Vision and calibration: `available_cameras`, `capture_image`, `pixel_to_robot_offset`
- Utilities: `set_color`, `set_default_speed`

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
- After `power_off()` or an emergency stop, use `power_on()` before resuming normal motion commands.

### Gripper Rules

- The current driver targets the **electric gripper** by default.
- Use `init_gripper()` once after a power cycle before relying on `open_gripper()` or `close_gripper()`.
- Sequence gripper actions logically around motion:
  - open before approach if preparing to pick
  - close to grasp
  - open to release
- `set_gripper_value()` is for the adaptive gripper path and should not be the default recommendation unless the user explicitly indicates that hardware configuration.

### Camera Rules

- The current Elephant driver exposes **Pi camera only**.
- `available_cameras()` should be treated as Pi-only capability.
- Use `capture_image()` only when the workflow requires visual confirmation or CV input.
- If image-based offset correction is needed, use `pixel_to_robot_offset(...)` with a known `z_touch` and a calibrated camera setup.

### Command Dependencies and Sequencing

**Important**: If the user's request contains invalid commands, incorrect sequencing, or violates driver constraints, **do not blindly follow the request**. Explain the issue and correct the command sequence.

**Critical sequencing rules:**
1. Ensure the robot is connected and powered before motion commands.
2. After `power_off()` or emergency stop, call `power_on()` before further motion.
3. Before electric-gripper open/close operations after a power cycle, call `init_gripper()`.
4. Before camera-guided work, prefer moving to `scan()` first unless the workflow requires capture from another known-safe pose.
5. If a workflow ends in an uncertain or faulted state, prefer `reset()` or `scan()` rather than leaving the arm at an arbitrary pose.

## Instructions

1. **Consult Resources**: Consult the resources listed in the "Required Resources" section above before generating any commands.
2. **Verify sequencing and constraints**: Ensure motion, power, gripper, and camera steps are ordered safely and coherently for the requested workflow.
3. **Generate command**: Create command objects with `machine_id: "elephant"`, the appropriate command `name`, and valid `params`.
