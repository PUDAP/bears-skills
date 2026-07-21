---
name: puda-machine-vision-validation
description: Use before physical PUDA workflows at BEARS when execution depends on visually verifiable machine setup, workspace occupancy, fixtures, labware, targets, tools, cables, or addressable positions. Capture a fresh image, apply the selected machine profile, compare expected versus observed state, and block motion when evidence is uncertain or mismatched.
---

# PUDA Machine Vision Validation

## Goal

Provide one machine-neutral visual safety gate for PUDA-connected machines at BEARS. Validate the current physical scene before motion or execution without assuming every machine has an Opentrons-style deck, slots, labware, or row/column coordinates.

This skill validates visible physical state. It does not replace protocol validation, machine telemetry, calibration, interlocks, homing requirements, or operator approval.

## When to Use

Use this skill when a PUDA workflow depends on any visually checkable condition, including:

- deck, stage, tray, pan, holder, fixture, cell, vessel, tool, gripper, or target placement
- required-empty or keep-out regions
- addressable wells, tips, channels, samples, bins, or grid positions
- camera-guided alignment, pickup, placement, or inspection
- user requests for vision validation without execution

Use the machine-specific profile selected from `bears-machines`. Do not force vision validation onto a machine that has no suitable current image source or whose critical state cannot be established visually.

## No-Execution Boundary

For a validation-only request:

- allowed: read the planned protocol, inspect machine definitions, capture a passive fresh frame, crop/rectify/annotate copies, compare with authoritative references, hash evidence, and report the gate result
- prohibited: home, jog, scan, move, grip, pick, dispense, tare, start a run, reset faults, energize outputs, or change machine state unless the user separately authorizes that action

A camera command can itself move hardware or alter machine state. Prefer an already-configured passive stream or snapshot endpoint. If capture requires motion (for example, moving an arm to a scan pose), ask for approval before moving.

## Machine Profile Contract

Before inspection, build or load a profile containing:

| Field | Requirement |
|---|---|
| `machine_id` | Exact PUDA machine identifier |
| `image_source` | Passive stream/snapshot or approved capture command |
| `camera_pose` | Named/fixed pose and calibration validity, when applicable |
| `workspace_model` | Slots, zones, trays, fixtures, stages, pans, channels, or free-space regions |
| `expected_objects` | Required object, identity/category, role, and expected region |
| `required_states` | Open/closed, occupied/empty, attached/detached, aligned, connected, etc. |
| `coordinate_model` | Optional named positions and their authoritative definition |
| `reference_sources` | Official library, driver docs, machine drawings, labels, or current project record |
| `safety_gate` | Which uncertain/mismatched observations block execution |

If any field needed for the requested check is missing and cannot be retrieved, report that limitation instead of borrowing an Opentrons convention.

## Machine Selection and Adapters

Load `bears-machines`, select the exact machine, then apply the matching adapter:

### Opentrons OT-2 (`machine_id: opentrons`)

Use [puda-opentrons-vision-validation](../puda-opentrons-vision-validation/SKILL.md) as the detailed adapter. It defines the 12-slot deck, labware identification, A1–H12 handling, tip-presence checks, and perspective-aligned slot polygons.

### First Machine (`machine_id: first`)

Use the deck/workspace definition in `bears-machines/references/first-machine.md` and the live output of `puda machine commands first`. Validate only regions and address names defined there or in the current protocol. Do not assume OT-2 slot numbers, labware dimensions, pipette mounts, or trash location.

### Elephant Pro630 (`machine_id: elephant`)

Use `bears-machines/references/elephant.md`. Record the active camera, camera pose, calibration, target description, gripper/tool state, pickup/placement regions, and keep-out zones. A fresh image from an unknown or changed camera pose cannot prove robot coordinates. Vision validation alone must not initiate `scan`, arm motion, or gripper motion.

### Balance (`machine_id: balance`)

Vision may confirm that a vessel is centered on the pan and that the surrounding area appears clear when a suitable camera exists. It cannot prove tare state, calibrated mass, serial connectivity, or data freshness; verify those through balance telemetry and the balance workflow.

### Biologic (`machine_id: biologic`)

Validate visible cell/fixture/cable placement only when the camera view and expected connection map are explicitly available. An image cannot prove channel configuration, electrical continuity, voltage limits, or test readiness; use driver state and the Biologic workflow for those checks.

### Other or New Machines

Create a profile from the contract above using official driver/docs and the current workflow. Use machine-native region names. If no safe fresh image can be captured, return `not visible` and keep the execution gate closed.

## Evidence Policy

Every validation is independent and must use:

1. the current user request or current protocol as the expected scene,
2. a fresh image captured for this validation, and
3. current machine-specific authoritative references.

Do not carry object identity, occupancy, orientation, or alignment confirmations from an earlier capture into a new validation. Earlier corrections may improve the inspection method but do not prove the current scene.

Record:

- capture time and provenance
- machine ID and camera/pose identifier
- image path, non-zero size, and SHA-256
- whether capture was passive or required an approved command
- any cropping, perspective correction, or enhancement applied to copies

Never expose camera credentials or secret connection strings in reports or committed files.

## Region and Perspective Alignment

Annotate according to the machine's physical workspace geometry:

1. Identify visible physical boundary intersections from the fresh image.
2. Build shared nodes/edges for adjacent regions; do not estimate every region independently.
3. Use perspective-aware polygons or a calibrated homography when the camera is tilted.
4. Cover each complete physical region from boundary to boundary without entering a neighbour.
5. Anchor boundaries to the machine/workspace outline, not to an object's footprint.
6. Preserve an unannotated evidence image and independently verify the final overlay.

For irregular workspaces, use named polygons or keep-out zones rather than forcing rectangles. If a boundary is occluded or cannot be calibrated, mark the affected region `not visible` or `obstructed`.

## Addressable Positions and Occupancy

When the user names a position:

1. Validate the coordinate against the exact machine/labware/fixture definition.
2. Establish physical orientation from a visible marker or authoritative cue.
3. Crop the full object, including edge rows/columns needed to count from the origin.
4. If needed, perspective-rectify the crop internally.
5. Do **not** draw a row/column grid over tips, wells, samples, or targets.
6. Count from the established origin and compare the requested position with its immediate neighbours in a clean crop.
7. Optionally add one small circle/arrow while retaining an unannotated crop.
8. Assign an explicit status: `present`, `absent`, `needs confirmation`, or `not visible`.

Do not infer one position's occupancy from general rack/tray fullness unless every position is individually visible and the conclusion is orientation-independent.

## Validation Workflow

### 1. Build the expected scene

List every machine, region, object, state, coordinate, and required-empty/keep-out area that affects the planned action.

Completion criterion: every physical precondition used by the workflow has a named expected observation or is explicitly classified as non-visual telemetry.

### 2. Capture fresh evidence

Use the selected machine profile's passive image source. If no passive path exists, determine whether the capture command can move or alter hardware and obtain approval when required.

Completion criterion: a fresh non-empty image exists with provenance, time, and hash.

### 3. Inspect conservatively

For each expected region/object/state, report visibility, occupancy/state, observed category or identity, confidence, and supporting visual cue. Compare exact identity with official references when geometry affects safe operation.

Completion criterion: all expected regions plus unexpected occupied/obstructed/keep-out regions are covered.

### 4. Compare expected versus observed

Use:

| Status | Meaning |
|---|---|
| `OK` | Expected state is visible and supported with adequate confidence |
| `needs confirmation` | Region/state is visible but exact identity or condition is uncertain |
| `MISMATCH` | Visible state conflicts with expected state |
| `not visible` | Framing, pose, occlusion, or resolution prevents verification |
| `obstructed` | Another item prevents inspection or occupies a required clear region |

### 5. Gate execution

- Continue only when every required visual condition is `OK` and every non-visual safety prerequisite is separately satisfied.
- `needs confirmation`, `MISMATCH`, `not visible`, and `obstructed` keep the gate closed unless the user explicitly accepts the stated risk.
- A user correction applies only to the current image. If physical setup changes, capture again.
- Vision approval does not authorize robot execution; retain any separate protocol approval requirement.

## Output Format

Report:

1. **Machine and evidence** — machine ID, camera/pose, capture time, path/hash.
2. **Expected-vs-observed table** — region, expected, observed, confidence, status.
3. **Unexpected observations** — occupied, obstructed, or unsafe regions.
4. **Coordinate checks** — requested position and occupancy/state, without a grid overlay.
5. **Non-visual prerequisites** — telemetry/calibration/interlocks that remain unverified.
6. **Gate decision** — pass, blocked, or needs confirmation.
7. **Execution statement** — explicitly state whether any machine command or motion occurred.

## Common Pitfalls

- Applying OT-2 slots, A1 orientation, or labware rules to another machine.
- Moving an arm to improve the camera view during a validation-only request.
- Treating a camera image as proof of calibration, tare, electrical continuity, or telemetry freshness.
- Drawing region boxes from object footprints instead of physical workspace outlines.
- Drawing a full coordinate grid over positions rather than inspecting a clean crop.
- Reusing old confirmations as evidence for a fresh scene.
- Reporting an exact object identity from colour alone.
- Passing a gate when the camera pose or workspace calibration is unknown.

## Verification Checklist

- [ ] Exact machine and machine profile selected.
- [ ] Expected physical scene extracted from the current request/protocol.
- [ ] Visual versus non-visual prerequisites separated.
- [ ] Passive capture used, or motion/state-changing capture separately approved.
- [ ] Fresh image path, time, size, hash, camera, and pose recorded.
- [ ] Physical regions aligned using shared perspective-aware boundaries.
- [ ] Clean unannotated evidence retained.
- [ ] No coordinate grid drawn over objects or positions.
- [ ] Every requested position validated against its exact definition and assigned a status.
- [ ] Expected and unexpected regions inspected.
- [ ] Current official machine references used.
- [ ] Gate closed for every uncertain, mismatched, obstructed, or invisible required condition.
- [ ] Final report states whether any command or motion occurred.
