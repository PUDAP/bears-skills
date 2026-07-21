# Opentrons Labware Library visual-identification reference

Authoritative source: [Opentrons Labware Library](https://labware.opentrons.com/)

Last verified against the live library: 2026-07-21.

## Purpose

Use the official library's product names, API load names, categories, and reference photographs when identifying labware observed in fresh OT-2 deck images. The live library is authoritative and may change; consult it at identification time rather than relying only on remembered colour or shape.

## Library categories

- [Well Plates](https://labware.opentrons.com/#/?category=wellPlate)
- [Tip Racks](https://labware.opentrons.com/#/?category=tipRack)
- [Reservoirs](https://labware.opentrons.com/#/?category=reservoir)
- [Tube Racks](https://labware.opentrons.com/#/?category=tubeRack)
- [Aluminum Blocks](https://labware.opentrons.com/#/?category=aluminumBlock)
- [Adapters](https://labware.opentrons.com/#/?category=adapter)
- [Lids](https://labware.opentrons.com/#/?category=lid)

## Common BEARS OT-2 candidates

| Display name | API load name | Official detail page | Official reference image |
|---|---|---|---|
| Corning 96 Well Plate 360 µL Flat | `corning_96_wellplate_360ul_flat` | https://labware.opentrons.com/#/?loadName=corning_96_wellplate_360ul_flat | https://labware.opentrons.com/labware-images/corning_96_wellplate_360ul_flat.jpg |
| Corning 96 Well Plate 330 µL | `corning_96_wellplate_330ul` | https://labware.opentrons.com/#/?loadName=corning_96_wellplate_330ul | https://labware.opentrons.com/labware-images/corning_96_wellplate_330ul.jpg |
| Opentrons OT-2 96 Tip Rack 1000 µL | `opentrons_96_tiprack_1000ul` | https://labware.opentrons.com/#/?loadName=opentrons_96_tiprack_1000ul | https://labware.opentrons.com/labware-images/opentrons_96_tiprack_1000ul.jpg |
| Opentrons OT-2 96 Tip Rack 300 µL | `opentrons_96_tiprack_300ul` | https://labware.opentrons.com/#/?loadName=opentrons_96_tiprack_300ul | https://labware.opentrons.com/labware-images/opentrons_96_tiprack_300ul.jpg |
| Opentrons OT-2 96 Filter Tip Rack 1000 µL | `opentrons_96_filtertiprack_1000ul` | https://labware.opentrons.com/#/?loadName=opentrons_96_filtertiprack_1000ul | https://labware.opentrons.com/labware-images/opentrons_96_filtertiprack_1000ul.jpg |
| Opentrons OT-2 96 Filter Tip Rack 200 µL | `opentrons_96_filtertiprack_200ul` | https://labware.opentrons.com/#/?loadName=opentrons_96_filtertiprack_200ul | https://labware.opentrons.com/labware-images/opentrons_96_filtertiprack_200ul.jpg |

This table is a shortcut, not a complete catalogue. Use the live library for other labware and distinguish OT-2 items from Flex items.

## Identification workflow

1. Map the deck accurately and crop the occupied slot without including neighbouring slots where possible.
2. Classify the broad category from geometry: tiprack, well plate, reservoir, tube rack, block, adapter, lid, or trash bin.
3. Open the matching live-library category and compare plausible candidates, prioritizing the labware expected by the protocol or user.
4. Compare structural cues, not colour alone:
   - number and arrangement of wells/tip positions
   - well shape and spacing
   - plate/rack height and skirt/frame geometry
   - tip length and whether tips are filtered
   - labels, molded markings, lids, and adapters when visible
   - OT-2 versus Flex form factor
5. Report the best candidate using both display name and API load name, link the official detail page, and state confidence.
6. Treat an exact match as `OK` only when the image has adequate detail and it agrees with the expected deck map or a user confirmation. If multiple definitions remain visually plausible, report the candidates and mark `needs confirmation`.
7. Treat user corrections as evidence only for the current fresh image and current validation. Do not carry a user-confirmed identity or slot assignment from an earlier capture into a later validation; re-identify from the later image and official references.

## Confidence wording

- **High:** category and exact model/load name are supported by distinctive visible geometry and expected setup or user confirmation.
- **Medium:** category is clear and one official candidate is strongest, but similar definitions cannot be excluded.
- **Low:** only broad occupancy/category is visible; do not assert an exact API load name.

## Safety limitation

Official catalogue photographs are usually product shots, while deck-camera images are top-down, lower resolution, partially filled, and affected by perspective. Visual comparison improves identification but cannot guarantee an exact definition. Never let an image-only guess override a mismatch or replace user confirmation when exact identity affects pipetting geometry.
