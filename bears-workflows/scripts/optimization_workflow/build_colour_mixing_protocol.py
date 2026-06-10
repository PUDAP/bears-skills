"""Build Opentrons Python protocols for colour-mixing experiments.

The generated protocol intentionally uses explicit low-level pipetting calls.
Avoid ``transfer()``, ``distribute()``, air gaps, and mix helpers here: those
helpers can introduce extra aspirate-like motions such as disposal volume,
refills, or mix cycles that are hard to see from the optimizer volumes alone.
"""

from __future__ import annotations

from dataclasses import dataclass


COMPONENTS: tuple[tuple[str, str, str], ...] = (
    ("R", "red_plate", "r_source_well"),
    ("G", "green_plate", "g_source_well"),
    ("B", "blue_plate", "b_source_well"),
    ("water", "water_plate", "water_source_well"),
)

VOLUME_KEYS: dict[str, tuple[str, ...]] = {
    "R": ("R", "R_vol", "red", "Red"),
    "G": ("G", "G_vol", "green", "Green"),
    "B": ("B", "B_vol", "blue", "Blue"),
    "water": ("water", "water_vol", "Water"),
}


@dataclass
class ColourMixingDeckConfig:
    """Deck layout for a four-source colour-mixing run."""

    r_slot: str
    g_slot: str
    b_slot: str
    water_slot: str
    dest_slot: str
    tiprack_slot: str
    labware_type: str = "corning_96_wellplate_360ul_flat"
    tiprack_type: str = "opentrons_96_tiprack_300ul"
    pipette: str = "p300_single_gen2"
    pipette_mount: str = "right"
    r_source_well: str = "A1"
    g_source_well: str = "A1"
    b_source_well: str = "A1"
    water_source_well: str = "A1"
    api_level: str = "2.23"


def _volume(mix: dict, component: str) -> float:
    for key in VOLUME_KEYS[component]:
        if key in mix:
            return float(mix[key])
    return 0.0


def count_required_tips(mixes: list[dict]) -> int:
    """Return how many tips a mix list consumes: one per non-zero component."""

    total = 0
    for mix in mixes:
        for component, _, _ in COMPONENTS:
            if _volume(mix, component) > 0:
                total += 1
    return total


def build_colour_mixing_protocol(
    mixes: list[dict],
    deck: ColourMixingDeckConfig,
    *,
    starting_tip: str | None = None,
    protocol_name: str = "Colour Mixing",
) -> str:
    """Generate Opentrons API Python source for one or more colour mixes.

    Each mix dict must include ``well`` or ``dest_well`` plus component volumes.
    Components with volume <= 0 are skipped.

    The generated sequence is deliberately strict:
    pick up one fresh tip, aspirate one component once, dispense once, blow out,
    drop the tip, then continue to the next component with a new tip.
    """

    if not mixes:
        raise ValueError("At least one mix is required.")

    lines: list[str] = [
        "from opentrons import protocol_api",
        "",
        "metadata = {",
        f'    "protocolName": "{protocol_name}",',
        '    "author": "PUDA colour-mixing workflow",',
        f'    "description": "Colour mixing - {len(mixes)} well(s), explicit fresh-tip aspirate/dispense",',
        f'    "apiLevel": "{deck.api_level}",',
        "}",
        "",
        "def run(protocol: protocol_api.ProtocolContext):",
        f'    tiprack = protocol.load_labware("{deck.tiprack_type}", "{deck.tiprack_slot}")',
        f'    red_plate = protocol.load_labware("{deck.labware_type}", "{deck.r_slot}")',
        f'    green_plate = protocol.load_labware("{deck.labware_type}", "{deck.g_slot}")',
        f'    blue_plate = protocol.load_labware("{deck.labware_type}", "{deck.b_slot}")',
        f'    water_plate = protocol.load_labware("{deck.labware_type}", "{deck.water_slot}")',
        f'    dest_plate = protocol.load_labware("{deck.labware_type}", "{deck.dest_slot}")',
        "    pipette = protocol.load_instrument(",
        f'        "{deck.pipette}",',
        f'        mount="{deck.pipette_mount}",',
        "        tip_racks=[tiprack],",
        "    )",
    ]

    if starting_tip:
        lines.append(f'    pipette.starting_tip = tiprack["{starting_tip}"]')

    lines.append("    protocol.home()")

    source_well_by_plate = {
        "red_plate": deck.r_source_well,
        "green_plate": deck.g_source_well,
        "blue_plate": deck.b_source_well,
        "water_plate": deck.water_source_well,
    }

    for mix in mixes:
        dest_well = mix.get("well") or mix.get("dest_well")
        if not dest_well:
            raise ValueError(f"Mix missing destination well: {mix!r}")

        lines.append(f"    # Destination well {dest_well}")
        for component, plate_var, _source_attr in COMPONENTS:
            volume = _volume(mix, component)
            if volume <= 0:
                continue

            src_well = source_well_by_plate[plate_var]
            lines.extend(
                [
                    "    pipette.pick_up_tip()",
                    f'    pipette.aspirate({volume:.4g}, {plate_var}["{src_well}"].bottom(1))',
                    f'    pipette.dispense({volume:.4g}, dest_plate["{dest_well}"].bottom(2))',
                    f'    pipette.blow_out(dest_plate["{dest_well}"].top())',
                    "    pipette.drop_tip()",
                ]
            )

    lines.append("    protocol.home()")
    return "\n".join(lines) + "\n"
