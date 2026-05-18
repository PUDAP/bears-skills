from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "elephant"
    / "alignment.py"
)

spec = importlib.util.spec_from_file_location("elephant_alignment", MODULE_PATH)
alignment = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["elephant_alignment"] = alignment
spec.loader.exec_module(alignment)


YoloCandidate = alignment.YoloCandidate
check_inner_tape_alignment = alignment.check_inner_tape_alignment


def candidate(index, bbox, cls_name, confidence=0.9):
    x1, y1, x2, y2 = bbox
    return YoloCandidate(
        index=index,
        bbox=bbox,
        cx=(x1 + x2) // 2,
        cy=(y1 + y2) // 2,
        cls_name=cls_name,
        confidence=confidence,
    )


def base_tapes():
    return [
        candidate(1, (80, 80, 100, 240), "silver_tape", 0.95),
        candidate(2, (150, 82, 170, 242), "silver_tape", 0.94),
    ]


def test_alignment_succeeds_when_target_center_is_between_inner_tape_edges():
    candidates = [
        *base_tapes(),
        candidate(3, (115, 120, 135, 175), "blue_cap_vial", 0.91),
    ]

    result = check_inner_tape_alignment(
        candidates,
        image_size=(320, 240),
        target_name="blue cap vial",
    )

    assert result.aligned is True
    assert result.object_visible is True
    assert result.gripper_cx == 125
    assert result.object_cx == 125
    assert result.offset_px == 0
    assert result.suggestion == "none"


def test_alignment_suggests_left_when_target_is_left_of_inner_tape_center():
    candidates = [
        *base_tapes(),
        candidate(3, (103, 120, 123, 175), "blue_cap_vial", 0.91),
    ]

    result = check_inner_tape_alignment(
        candidates,
        image_size=(320, 240),
        target_name="blue cap vial",
    )

    assert result.aligned is False
    assert result.object_cx == 113
    assert result.gripper_cx == 125
    assert result.offset_px == -12
    assert result.suggestion == "left"
    assert result.correction_y_mm == pytest.approx(-4.2)


def test_alignment_suggests_right_when_target_is_right_of_inner_tape_center():
    candidates = [
        *base_tapes(),
        candidate(3, (127, 120, 147, 175), "blue_cap_vial", 0.91),
    ]

    result = check_inner_tape_alignment(
        candidates,
        image_size=(320, 240),
        target_name="blue cap vial",
    )

    assert result.aligned is False
    assert result.object_cx == 137
    assert result.gripper_cx == 125
    assert result.offset_px == 12
    assert result.suggestion == "right"
    assert result.correction_y_mm == pytest.approx(4.2)


def test_alignment_fails_when_target_is_missing():
    result = check_inner_tape_alignment(
        base_tapes(),
        image_size=(320, 240),
        target_name="blue cap vial",
    )

    assert result.aligned is False
    assert result.object_visible is False
    assert result.suggestion == "none"
    assert "no CAM2 target" in result.reason


def test_alignment_fails_when_two_tape_markers_are_missing():
    candidates = [
        candidate(1, (80, 80, 100, 240), "silver_tape", 0.95),
        candidate(2, (115, 120, 135, 175), "blue_cap_vial", 0.91),
    ]

    result = check_inner_tape_alignment(
        candidates,
        image_size=(320, 240),
        target_name="blue cap vial",
    )

    assert result.aligned is False
    assert result.object_visible is False
    assert result.suggestion == "none"
    assert "two tape marker boxes" in result.reason
