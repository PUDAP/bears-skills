from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "RSI optimization"
    / "build_colour_mixing_protocol.py"
)


def load_module():
    name = "rsi_build_colour_mixing_protocol_test"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_tiprack_offset_is_encoded_in_generated_protocol():
    module = load_module()
    deck = module.ColourMixingDeckConfig(
        r_slot="6",
        g_slot="3",
        b_slot="2",
        water_slot="1",
        dest_slot="5",
        tiprack_slot="8",
        tiprack_offset_x=0.0,
        tiprack_offset_y=2.0,
        tiprack_offset_z=0.0,
    )

    code = module.build_colour_mixing_protocol(
        [{"well": "A1", "R": 40, "G": 220, "B": 40, "water": 0}],
        deck,
        starting_tip="A1",
    )

    assert "tiprack.set_offset(x=0.0, y=2.0, z=0.0)" in code
    assert 'pipette.pick_up_tip(tiprack["A1"])' in code
    assert 'pipette.pick_up_tip(tiprack["A2"])' in code
    assert 'pipette.pick_up_tip(tiprack["A3"])' in code
    assert code.count("pipette.pick_up_tip(") == 3
