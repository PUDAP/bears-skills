---
name: example
description: Create a P-shaped liquid pattern on an Opentrons OT-2 destination plate using explicit aspirate and dispense operations.
---

# Example P-Shape Workflow

Use this workflow to create a visible letter `P` on a 96-well plate by dispensing the same liquid into a fixed set of wells.

## Required Machine

- Opentrons OT-2 (`machine_id: "opentrons"`)

## Required Inputs

Ask the user to confirm these before generating or running the protocol:

| Input | Description |
|---|---|
| Source liquid | The liquid to dispense, such as dye or water |
| Source labware type | Labware holding the source liquid |
| Source labware deck slot | OT-2 deck slot for the source labware |
| Source well | Well containing the source liquid, for example `A1` |
| Destination labware type | Usually `corning_96_wellplate_360ul_flat` |
| Destination labware deck slot | OT-2 deck slot for the destination plate |
| Tip rack type | Usually `opentrons_96_tiprack_300ul` |
| Tip rack deck slot | OT-2 deck slot for the tip rack |
| Pipette type and mount | For example `p300_single_gen2` on `right` |
| Dispense volume | Volume per destination well in uL |

## P-Shape Wells

The default P shape uses these destination wells:

```text
A1 A2 A3 A4
B1       B4
C1       C4
D1 D2 D3 D4
E1
F1
G1
H1
```

Well list:

```python
("A1", "A2", "A3", "A4", "B1", "B4", "C1", "C4", "D1", "D2", "D3", "D4", "E1", "F1", "G1", "H1")
```

## Protocol Generation

Use [scripts/example/p_shape.py](../../scripts/example/p_shape.py) to generate OT-2 Python protocol code.

The generated protocol:

1. Loads the tip rack, source labware, and destination plate.
2. Loads the configured pipette.
3. Homes the robot.
4. Picks up one tip.
5. Repeats one `aspirate` and one `dispense` per P-shape well.
6. Blows out at the destination well top after each dispense.
7. Drops the tip and homes the robot.

## Rules

- Do not assume deck slots; ask the user to confirm them.
- Dispense volume must be greater than `0` and within the selected pipette capacity.
- Use explicit `pipette.aspirate(...)` and `pipette.dispense(...)`; do not use `transfer()` or `distribute()` for this example.
- The protocol must end with no tip attached.
