from pathlib import Path
import csv
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.optimization_workflow.image_processing import (
    DEFAULT_CONFIG,
    ImageConfig,
    create_capture_calibration,
    interpolate_well_centers,
    mean_rgb,
    run_pipeline,
    save_inner_roi_debug_image,
    save_roi_debug_image,
    slice_inner_well_patches,
    validate_capture_calibration,
)


def test_capture_calibration_is_stamped_and_bound_to_image(tmp_path):
    image_path = tmp_path / "capture-001.png"
    Image.fromarray(np.zeros((100, 140, 3), dtype=np.uint8)).save(image_path)
    config = create_capture_calibration(
        capture_id="capture-001",
        calibration_image_path=str(image_path),
        raw_image_size=(140, 100),
        src_corners=[(5, 5), (135, 5), (135, 95), (5, 95)],
        well_center_corners=[(15, 15), (125, 15), (125, 85), (15, 85)],
    )

    validate_capture_calibration(config, "capture-001", str(image_path))
    assert config.calibration_capture_id == "capture-001"
    assert config.calibration_image_path == str(image_path.resolve())
    assert config.calibration_image_sha256
    assert config.calibrated_at_utc


def test_default_config_matches_verified_bears_hd_calibration():
    assert DEFAULT_CONFIG.src_corners == [(678, 436), (949, 436), (949, 618), (678, 618)]
    assert DEFAULT_CONFIG.well_center_corners == [
        (712, 459),
        (920, 460),
        (919, 592),
        (711, 592),
    ]
    assert DEFAULT_CONFIG.inner_roi_size == 8


def test_inner_well_patches_stay_inside_synthetic_wells():
    image = np.full((100, 140, 3), 240, dtype=np.uint8)
    corners = [(15.0, 15.0), (125.0, 15.0), (125.0, 85.0), (15.0, 85.0)]
    centers = interpolate_well_centers(corners, col_num=12, row_num=8)

    expected_colours = []
    for idx, (center_x, center_y) in enumerate(centers):
        colour = np.array([(idx * 3) % 256, (idx * 5) % 256, (idx * 7) % 256], dtype=np.uint8)
        expected_colours.append(tuple(int(value) for value in colour))
        for y in range(int(center_y) - 6, int(center_y) + 7):
            for x in range(int(center_x) - 6, int(center_x) + 7):
                if (x - center_x) ** 2 + (y - center_y) ** 2 <= 36:
                    image[y, x] = colour

    patches, boxes = slice_inner_well_patches(
        image, corners, col_num=12, row_num=8, roi_size=8
    )

    assert len(patches) == 96
    assert len(boxes) == 96
    assert all(patch.shape == (8, 8, 3) for patch in patches)
    assert [mean_rgb(patch) for patch in patches] == expected_colours


def test_fractional_centers_keep_order_and_exact_patch_size():
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    corners = [(15.25, 14.75), (143.75, 16.25), (141.5, 103.75), (16.5, 102.25)]

    centers = interpolate_well_centers(corners, col_num=12, row_num=8)
    patches, boxes = slice_inner_well_patches(
        image, corners, col_num=12, row_num=8, roi_size=8
    )

    assert len(centers) == 96
    assert centers[0] == corners[0]
    assert centers[11] == corners[1]
    assert centers[84] == corners[3]
    assert centers[95] == corners[2]
    assert all((x2 - x1, y2 - y1) == (8, 8) for x1, y1, x2, y2 in boxes)
    assert all(patch.shape == (8, 8, 3) for patch in patches)


def test_debug_rectangle_matches_half_open_crop_bounds(tmp_path):
    raw = np.zeros((24, 24, 3), dtype=np.uint8)
    output = tmp_path / "debug.png"

    save_inner_roi_debug_image(
        raw,
        [(5, 5, 13, 13)],
        str(output),
        col_num=1,
        row_num=1,
    )

    debug = np.array(Image.open(output).convert("RGB"))
    assert tuple(debug[12, 12]) == (0, 255, 255)
    assert tuple(debug[12, 13]) == (0, 0, 0)


def test_legacy_debug_uses_half_open_bounds_and_supports_nine_rows(tmp_path):
    raw = np.zeros((120, 40, 3), dtype=np.uint8)
    boxes = []
    for row in range(9):
        for col in range(2):
            x1 = 4 + col * 16
            y1 = 4 + row * 12
            boxes.append((x1, y1, x1 + 8, y1 + 8))
    output = tmp_path / "legacy_debug.png"

    save_roi_debug_image(
        raw,
        boxes,
        str(output),
        col_num=2,
        row_num=9,
        outline_colour=(0, 255, 255),
        outline_width=1,
    )

    debug = np.array(Image.open(output).convert("RGB"))
    first_x1, first_y1, first_x2, first_y2 = boxes[0]
    assert tuple(debug[first_y2 - 1, first_x2 - 1]) == (0, 255, 255)
    assert tuple(debug[first_y2 - 1, first_x2]) == (0, 0, 0)
    assert output.exists()


def test_mean_rgb_uses_arithmetic_mean_not_median():
    patch = np.array([[[0, 0, 0], [0, 0, 0]], [[0, 0, 0], [100, 40, 20]]], dtype=np.uint8)

    assert mean_rgb(patch) == (25, 10, 5)


def test_run_pipeline_writes_inner_roi_artifacts(tmp_path):
    raw = np.full((100, 140, 3), 245, dtype=np.uint8)
    corners = [(15.0, 15.0), (125.0, 15.0), (125.0, 85.0), (15.0, 85.0)]
    centers = interpolate_well_centers(corners, col_num=12, row_num=8)
    for idx, (center_x, center_y) in enumerate(centers):
        colour = np.array([30 + idx, 20 + idx, 10 + idx], dtype=np.uint8)
        x1, y1 = round(center_x - 4), round(center_y - 4)
        raw[y1 : y1 + 8, x1 : x1 + 8] = colour

    image_path = tmp_path / "plate.png"
    Image.fromarray(raw).save(image_path)
    config = create_capture_calibration(
        capture_id="plate-capture",
        calibration_image_path=str(image_path),
        raw_image_size=(140, 100),
        src_corners=[(5, 5), (135, 5), (135, 95), (5, 95)],
        well_center_corners=corners,
        inner_roi_size=8,
    )

    result = run_pipeline(
        str(image_path), ["A1", "H12"], config=config,
        calibration_capture_id="plate-capture",
    )

    assert result == {"A1": (30, 20, 10), "H12": (125, 115, 105)}
    assert (tmp_path / "plate_warped.png").exists()
    assert (tmp_path / "plate_roi_debug.png").exists()
    assert (tmp_path / "plate_roi_patches.png").exists()
    csv_path = tmp_path / "plate_rgb.csv"
    assert csv_path.exists()
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 96
    assert rows[0]["well"] == "A1"
    assert rows[-1]["well"] == "H12"
    assert rows[0]["coordinate_space"] == "raw"
    assert rows[0]["mean_R"] == "30"

    a1 = rows[0]
    reproduced = raw[
        int(a1["y1"]) : int(a1["y2_exclusive"]),
        int(a1["x1"]) : int(a1["x2_exclusive"]),
    ]
    assert reproduced.shape == (8, 8, 3)
    assert mean_rgb(reproduced) == (30, 20, 10)


def test_legacy_warped_grid_fallback_still_writes_artifacts(tmp_path):
    raw = np.zeros((20, 20, 3), dtype=np.uint8)
    raw[:10, :10] = (20, 30, 40)
    raw[10:, 10:] = (180, 190, 200)
    image_path = tmp_path / "legacy.png"
    Image.fromarray(raw).save(image_path)
    config = create_capture_calibration(
        capture_id="legacy-capture",
        calibration_image_path=str(image_path),
        raw_image_size=(20, 20),
        src_corners=[(0, 0), (19, 0), (19, 19), (0, 19)],
        well_center_corners=None,
    )
    config.dst_corners = [(0, 0), (20, 0), (20, 20), (0, 20)]
    config.plate_width = 20
    config.plate_height = 20
    config.col_num = 2
    config.row_num = 2
    config.offset_array = [[2, 2], [2, 2]]

    result = run_pipeline(
        str(image_path), ["A1", "B2"], config=config,
        calibration_capture_id="legacy-capture",
    )

    assert set(result) == {"A1", "B2"}
    assert (tmp_path / "legacy_warped.png").exists()
    assert (tmp_path / "legacy_roi_debug.png").exists()
    assert (tmp_path / "legacy_roi_patches.png").exists()
    with (tmp_path / "legacy_rgb.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4
    assert {row["coordinate_space"] for row in rows} == {"warped"}
