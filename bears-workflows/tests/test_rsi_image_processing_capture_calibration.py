import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "RSI optimization"
    / "image_processing.py"
)
SPEC = importlib.util.spec_from_file_location("rsi_capture_image_processing", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def synthetic_capture(path: Path) -> None:
    image = np.full((100, 140, 3), 245, dtype=np.uint8)
    corners = [(15.0, 15.0), (125.0, 15.0), (125.0, 85.0), (15.0, 85.0)]
    for index, (center_x, center_y) in enumerate(MODULE.interpolate_well_centers(corners, 12, 8)):
        colour = np.array([30 + index, 20 + index, 10 + index], dtype=np.uint8)
        x1, y1 = round(center_x - 4), round(center_y - 4)
        image[y1 : y1 + 8, x1 : x1 + 8] = colour
    Image.fromarray(image).save(path)


def make_calibration(image_path: Path, capture_id: str = "capture-001"):
    return MODULE.create_capture_calibration(
        capture_id=capture_id,
        calibration_image_path=str(image_path),
        raw_image_size=(140, 100),
        src_corners=[(5, 5), (135, 5), (135, 95), (5, 95)],
        well_center_corners=[(15, 15), (125, 15), (125, 85), (15, 85)],
        inner_roi_size=8,
    )


def test_capture_calibration_is_bound_to_exact_image_and_hash(tmp_path):
    image_path = tmp_path / "capture-001.png"
    synthetic_capture(image_path)
    config = make_calibration(image_path)

    result = MODULE.run_pipeline(
        str(image_path), ["A1", "H12"], config=config,
        calibration_capture_id="capture-001",
    )
    assert result == {"A1": (30, 20, 10), "H12": (125, 115, 105)}
    assert config.calibration_scope == "capture"
    assert config.calibration_image_sha256

    other_path = tmp_path / "capture-002.png"
    synthetic_capture(other_path)
    with pytest.raises(ValueError, match="does not match"):
        MODULE.run_pipeline(
            str(other_path), ["A1"], config=config,
            calibration_capture_id="capture-001",
        )

    # Replacing bytes at the same path must fail the SHA-256 gate rather than
    # being accepted merely because the filename and capture ID are unchanged.
    changed = np.zeros((100, 140, 3), dtype=np.uint8)
    Image.fromarray(changed).save(image_path)
    with pytest.raises(ValueError, match="hash differs"):
        MODULE.run_pipeline(
            str(image_path), ["A1"], config=config,
            calibration_capture_id="capture-001",
        )


def test_pipeline_rejects_default_and_run_scoped_calibration(tmp_path):
    image_path = tmp_path / "capture.png"
    synthetic_capture(image_path)
    with pytest.raises(ValueError, match="fresh capture-scoped"):
        MODULE.run_pipeline(
            str(image_path), ["A1"], config=MODULE.DEFAULT_CONFIG,
            calibration_capture_id="capture-001",
        )
    with pytest.raises(RuntimeError, match="Run-scoped calibration reuse is prohibited"):
        MODULE.create_run_calibration()


def test_pipeline_requires_matching_capture_id(tmp_path):
    image_path = tmp_path / "capture.png"
    synthetic_capture(image_path)
    config = make_calibration(image_path)
    with pytest.raises(ValueError, match="calibration_capture_id"):
        MODULE.run_pipeline(str(image_path), ["A1"], config=config)
    with pytest.raises(ValueError, match="another capture"):
        MODULE.run_pipeline(
            str(image_path), ["A1"], config=config,
            calibration_capture_id="capture-002",
        )


def test_exact_default_geometry_is_rejected_even_with_fresh_image(tmp_path):
    image_path = tmp_path / "hd.png"
    Image.fromarray(np.zeros((1080, 1920, 3), dtype=np.uint8)).save(image_path)
    with pytest.raises(ValueError, match="DEFAULT_CONFIG geometry"):
        MODULE.create_capture_calibration(
            capture_id="capture-hd",
            calibration_image_path=str(image_path),
            raw_image_size=(1920, 1080),
            src_corners=MODULE.DEFAULT_CONFIG.src_corners,
            well_center_corners=MODULE.DEFAULT_CONFIG.well_center_corners,
        )
