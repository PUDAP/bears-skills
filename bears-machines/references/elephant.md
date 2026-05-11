---
name: elephant-machine
description: Generate commands for the Elephant Pro630 robot arm, including Cartesian/joint motion, gripper control, scan/reset flows, and Pi-camera image capture.
---

# Elephant Machine Skills

Generate commands for the Elephant Pro630 6-axis robot arm.

## Purpose

This skill enables generation of commands for the Elephant machine in PUDA workflows. These commands automate robot-arm motion, gripper actions, and Pi-camera capture steps for vision-assisted operations.

## When to Use

Load this skill when:
- Users describe tasks to be executed on the Elephant robot arm
- Converting manual manipulation procedures into automated PUDA protocols
- Processing natural language requests for robot movement, positioning, or pick-and-place steps
- Working with workflows that require Pi-camera image capture from the Elephant setup

## Required Resources

**IMPORTANT**: Before generating any commands, **always consult these resources**:

1. **Consult CLI**: Run `puda machine commands elephant` to review available commands and parameters
2. **Driver Reference**: Ensure command intent matches Elephant driver behavior (motion, gripper, camera)

**Do not generate commands without first consulting these resources** to ensure accuracy and compatibility.

## Command Structure

Each Elephant command follows the standard protocol command structure (see protocol-generator reference). Key Elephant-specific details:

- `machine_id`: Must be `"elephant"` (string)

## Rules and Restrictions

The following rules **must** be strictly followed when generating Elephant commands:

### Handling Missing Information

- If required information is missing, **do not assume or guess** values. Use a placeholder value and ask the user for clarification.
- If a target pose/coordinate is not fully specified, ask for the missing axis values before finalizing motion commands.

### Motion and Safety

- Cartesian motion commands must use complete 6D poses (`x`, `y`, `z`, `rx`, `ry`, `rz`) when required by the command.
- Prefer moving to a known safe/scan position before camera capture or after recovery/reset flows.
- Use explicit speed values when user intent implies slow/precise vs fast transit movement.

### Gripper and Sequencing

- Ensure gripper actions are sequenced logically around motion (open before pickup approach, close to grasp, open to release).
- If an initialization command is required by the selected gripper workflow, include it before open/close operations.

### Camera Usage

- Use Pi-camera capture commands only when the workflow requires visual confirmation or CV inputs.
- If capture naming/path conventions are required by the workflow, follow them consistently to avoid overwriting outputs.

### Command Dependencies and Sequencing

**Important**: If the user's request contains invalid commands, incorrect sequencing, or violates constraints described in this document, **do not blindly follow the request**. Explain the issue and ask for correction.

## Instructions

1. **Consult Resources**: Consult the resources listed in the "Required Resources" section above before generating any commands.
2. **Verify sequencing and constraints**: Ensure motion, gripper, and camera steps are ordered safely and coherently for the requested workflow.
3. **Generate command**: Create command objects with `machine_id: "elephant"`, the appropriate command `name`, and valid `params`.
