"""Build an Opentrons protocol that dispenses a P shape on a well plate."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


P_SHAPE_WELLS: tuple[str, ...] = (
    "A1",
    "A2",
    "A3",
    "A4",
    "B1",
    "B4",
    "C1",
    "C4",
    "D1",
    "D2",
    "D3",
    "D4",
    "E1",
    "F1",
    "G1",
    "H1",
)


PIPETTE_MAX_VOLUME_UL: dict[str, float] = {
    "p10_single_gen2": 10,
    "p10_multi_gen2": 10,
    "p20_single_gen2": 20,
    "p20_multi_gen2": 20,
    "p300_single_gen2": 300,
    "p300_multi_gen2": 300,
    "p1000_single_gen2": 1000,
    "p1000_multi_gen2": 1000,
}


@dataclass(frozen=True)
class PShapeDeckConfig:
    source_slot: str
    dest_slot: str
    tiprack_slot: str
    source_labware_type: str
    dest_labware_type: str = "corning_96_wellplate_360ul_flat"
    tiprack_type: str = "opentrons_96_tiprack_300ul"
    pipette: str = "p300_single_gen2"
    pipette_mount: str = "right"
    source_well: str = "A1"
    api_level: str = "2.23"


def _validate(deck: PShapeDeckConfig, volume_ul: float) -> None:
    if volume_ul <= 0:
        raise ValueError("volume_ul must be greater than 0.")

    max_volume = PIPETTE_MAX_VOLUME_UL.get(deck.pipette)
    if max_volume is None:
        raise ValueError(f"Unsupported pipette type: {deck.pipette}")
    if volume_ul > max_volume:
        raise ValueError(
            f"volume_ul={volume_ul} exceeds {deck.pipette} capacity of {max_volume} uL."
        )


def build_p_shape_protocol(
    deck: PShapeDeckConfig,
    *,
    volume_ul: float = 20,
    protocol_name: str = "Example P Shape",
) -> str:
    """Generate Opentrons Python source for a P-shaped dispense pattern."""

    _validate(deck, volume_ul)

    lines: list[str] = [
        "from opentrons import protocol_api",
        "",
        "metadata = {",
        f'    "protocolName": "{protocol_name}",',
        '    "author": "PUDA example workflow",',
        '    "description": "Dispense a P shape with explicit aspirate and dispense calls",',
        f'    "apiLevel": "{deck.api_level}",',
        "}",
        "",
        "def run(protocol: protocol_api.ProtocolContext):",
        f'    tiprack = protocol.load_labware("{deck.tiprack_type}", "{deck.tiprack_slot}")',
        f'    source = protocol.load_labware("{deck.source_labware_type}", "{deck.source_slot}")',
        f'    dest_plate = protocol.load_labware("{deck.dest_labware_type}", "{deck.dest_slot}")',
        "    pipette = protocol.load_instrument(",
        f'        "{deck.pipette}",',
        f'        mount="{deck.pipette_mount}",',
        "        tip_racks=[tiprack],",
        "    )",
        "    protocol.home()",
        "    pipette.pick_up_tip()",
    ]

    for well in P_SHAPE_WELLS:
        lines.extend(
            [
                f'    pipette.aspirate({volume_ul:.4g}, source["{deck.source_well}"].bottom(1))',
                f'    pipette.dispense({volume_ul:.4g}, dest_plate["{well}"].bottom(2))',
                f'    pipette.blow_out(dest_plate["{well}"].top())',
            ]
        )

    lines.extend(
        [
            "    pipette.drop_tip()",
            "    protocol.home()",
        ]
    )
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an Opentrons protocol that dispenses a P shape."
    )
    parser.add_argument("--source-slot", required=True)
    parser.add_argument("--dest-slot", required=True)
    parser.add_argument("--tiprack-slot", required=True)
    parser.add_argument("--source-labware-type", required=True)
    parser.add_argument("--dest-labware-type", default="corning_96_wellplate_360ul_flat")
    parser.add_argument("--tiprack-type", default="opentrons_96_tiprack_300ul")
    parser.add_argument("--pipette", default="p300_single_gen2")
    parser.add_argument("--pipette-mount", default="right")
    parser.add_argument("--source-well", default="A1")
    parser.add_argument("--volume-ul", type=float, default=20)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    deck = PShapeDeckConfig(
        source_slot=args.source_slot,
        dest_slot=args.dest_slot,
        tiprack_slot=args.tiprack_slot,
        source_labware_type=args.source_labware_type,
        dest_labware_type=args.dest_labware_type,
        tiprack_type=args.tiprack_type,
        pipette=args.pipette,
        pipette_mount=args.pipette_mount,
        source_well=args.source_well,
    )
    protocol = build_p_shape_protocol(deck, volume_ul=args.volume_ul)
    if args.output:
        args.output.write_text(protocol, encoding="utf-8")
    else:
        print(protocol)


if __name__ == "__main__":
    main()
