from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimization_workflow.balance_data_process import analyze_viscosity_data


def test_aspirate_marker_survives_isolated_spike_filtering(tmp_path):
    raw = tmp_path / "aspirate_spike.csv"
    frame = pd.DataFrame(
        [
            {"time": 0.0, "mass_mg": 1.0, "command_type": ""},
            {"time": 1.0, "mass_mg": 2.0, "command_type": ""},
            {"time": 2.0, "mass_mg": 3881.0, "command_type": "aspirate"},
            {"time": 3.0, "mass_mg": 3.0, "command_type": "delay"},
            {"time": 4.0, "mass_mg": 4.0, "command_type": "delay"},
            {"time": 5.0, "mass_mg": 420.0, "command_type": "dispense"},
            {"time": 6.0, "mass_mg": 422.0, "command_type": "delay"},
            {"time": 7.0, "mass_mg": 421.0, "command_type": "delay"},
        ]
    )
    frame.to_csv(raw, index=False)

    result = analyze_viscosity_data(
        raw,
        tmp_path / "processed",
        outlier_threshold_mg=10_000.0,
        window_seconds=None,
    )

    assert result is not None
    assert (tmp_path / "processed" / raw.name).exists()
    assert result["Weight"].max() - result["Weight"].min() < 500.0
