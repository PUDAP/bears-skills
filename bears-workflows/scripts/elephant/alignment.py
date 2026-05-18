"""YOLO-only CAM2 gripper alignment helpers for the Elephant workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class YoloCandidate:
    index: int
    bbox: tuple[int, int, int, int]
    cx: int
    cy: int
    cls_name: str
    confidence: float


@dataclass(frozen=True)
class GripCheck:
    aligned: bool
    object_visible: bool
    object_cx: int | None
    gripper_cx: int | None
    offset_px: int
    correction_y_mm: float
    suggestion: str
    reason: str
    debug_path: str | None = None


@dataclass(frozen=True)
class AlignmentConfig:
    inner_line_tolerance_min_px: int = 5
    inner_line_tolerance_ratio: float = 0.12
    inner_line_tolerance_max_px: int = 8
    inner_tape_pair_min_gap_px: int = 2
    inner_tape_pair_max_gap_px: int = 180
    min_box_area: int = 150
    max_box_area_ratio: float = 0.80
    verify_mm_per_pixel: float = 0.35


def norm_name(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").lower()).strip("_")


def area_of(candidate: YoloCandidate) -> int:
    x1, y1, x2, y2 = candidate.bbox
    return max(0, int(x2) - int(x1)) * max(0, int(y2) - int(y1))


def is_tape_candidate(candidate: YoloCandidate) -> bool:
    cls = norm_name(candidate.cls_name)
    return "tape" in cls or "silver" in cls or "white_strip" in cls


def is_bad_alignment_candidate(candidate: YoloCandidate) -> bool:
    cls = norm_name(candidate.cls_name)
    return any(part in cls for part in ("gripper", "robot", "hand", "person", "arm"))


def matches_target(candidate: YoloCandidate, target_name: str) -> bool:
    target_norm = norm_name(target_name)
    cls = norm_name(candidate.cls_name)
    return bool(target_norm) and (cls == target_norm or cls in target_norm or target_norm in cls)


def _inner_edges(
    first: YoloCandidate,
    second: YoloCandidate,
) -> tuple[YoloCandidate, YoloCandidate, int, int, int, int]:
    left_tape, right_tape = sorted((first, second), key=lambda c: c.cx)
    left_inner_x = int(left_tape.bbox[2])
    right_inner_x = int(right_tape.bbox[0])
    center_x = int(round((left_inner_x + right_inner_x) / 2.0))
    gap_width = abs(right_inner_x - left_inner_x)
    return left_tape, right_tape, left_inner_x, right_inner_x, center_x, gap_width


def check_inner_tape_alignment(
    candidates: list[YoloCandidate],
    *,
    image_size: tuple[int, int],
    target_name: str,
    config: AlignmentConfig = AlignmentConfig(),
) -> GripCheck:
    """Return the CAM2 alignment state from YOLO candidates.

    `image_size` is `(width, height)`. The candidate list should contain YOLO
    detections from the CAM2 side/front camera.
    """
    width, height = image_size
    image_area = max(1, int(width) * int(height))

    sane: list[YoloCandidate] = []
    for candidate in candidates:
        area = area_of(candidate)
        if area < config.min_box_area:
            continue
        if area > config.max_box_area_ratio * image_area:
            continue
        sane.append(candidate)

    tape_candidates = [c for c in sane if is_tape_candidate(c)]
    target_candidates = [
        c for c in sane
        if not is_tape_candidate(c)
        and not is_bad_alignment_candidate(c)
        and matches_target(c, target_name)
    ]

    if not target_candidates:
        return GripCheck(
            aligned=False,
            object_visible=False,
            object_cx=None,
            gripper_cx=None,
            offset_px=0,
            correction_y_mm=0.0,
            suggestion="none",
            reason=f"YOLO found no CAM2 target matching {target_name!r}.",
        )

    if len(tape_candidates) < 2:
        return GripCheck(
            aligned=False,
            object_visible=False,
            object_cx=None,
            gripper_cx=None,
            offset_px=0,
            correction_y_mm=0.0,
            suggestion="none",
            reason="YOLO-only alignment needs two tape marker boxes.",
        )

    best: tuple[YoloCandidate, YoloCandidate, YoloCandidate, int, int, int, int, int] | None = None
    best_score: float | None = None

    top_tapes = sorted(tape_candidates, key=lambda c: float(c.confidence), reverse=True)[:8]
    top_targets = sorted(target_candidates, key=lambda c: float(c.confidence), reverse=True)[:8]

    for i, first_tape in enumerate(top_tapes):
        for second_tape in top_tapes[i + 1:]:
            left_tape, right_tape, left_inner_x, right_inner_x, center_x, gap_width = _inner_edges(
                first_tape,
                second_tape,
            )
            if gap_width < config.inner_tape_pair_min_gap_px:
                continue
            if gap_width > config.inner_tape_pair_max_gap_px:
                continue

            vertical_penalty = abs(left_tape.cy - right_tape.cy) * 0.15
            tape_bonus = 8.0 * (float(left_tape.confidence) + float(right_tape.confidence))

            for target in top_targets:
                offset_px = int(target.cx - center_x)
                target_bonus = 8.0 * float(target.confidence)
                score = abs(offset_px) + vertical_penalty - tape_bonus - target_bonus
                if best_score is None or score < best_score:
                    best_score = score
                    best = (
                        left_tape,
                        right_tape,
                        target,
                        left_inner_x,
                        right_inner_x,
                        center_x,
                        gap_width,
                        offset_px,
                    )

    if best is None:
        return GripCheck(
            aligned=False,
            object_visible=False,
            object_cx=None,
            gripper_cx=None,
            offset_px=0,
            correction_y_mm=0.0,
            suggestion="none",
            reason="Tape boxes were present, but no valid inner-line tape pair was selected.",
        )

    left_tape, right_tape, target, left_inner_x, right_inner_x, center_x, gap_width, offset_px = best
    tolerance_px = max(
        config.inner_line_tolerance_min_px,
        int(gap_width * config.inner_line_tolerance_ratio),
    )
    tolerance_px = min(tolerance_px, config.inner_line_tolerance_max_px)
    aligned = abs(offset_px) <= tolerance_px
    suggestion = "none" if aligned else ("left" if offset_px < 0 else "right")

    reason = (
        f"target=#{target.index} class={target.cls_name!r}, "
        f"left_tape=#{left_tape.index}, right_tape=#{right_tape.index}, "
        f"left_inner_x={left_inner_x}, right_inner_x={right_inner_x}, "
        f"gap_center_x={center_x}, object_x={target.cx}, "
        f"offset_px={offset_px}, tolerance_px=+/-{tolerance_px}, "
        f"gap_width={gap_width}."
    )

    return GripCheck(
        aligned=aligned,
        object_visible=True,
        object_cx=int(target.cx),
        gripper_cx=int(center_x),
        offset_px=int(offset_px),
        correction_y_mm=float(offset_px) * config.verify_mm_per_pixel,
        suggestion=suggestion,
        reason=reason,
    )


def draw_alignment_debug(
    image_path: str | Path,
    candidates: list[YoloCandidate],
    check: GripCheck,
    output_path: str | Path,
) -> str:
    """Draw a lightweight alignment debug overlay.

    Requires OpenCV. Import is intentionally local so the geometry helpers stay
    usable in environments without `cv2`.
    """
    import cv2

    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"Failed to read alignment image: {image_path}")

    h, _w = img.shape[:2]
    for candidate in candidates:
        x1, y1, x2, y2 = [int(v) for v in candidate.bbox]
        color = (0, 0, 255) if is_tape_candidate(candidate) else (0, 180, 180)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            img,
            f"{candidate.index}:{candidate.cls_name} {candidate.confidence:.2f}",
            (x1, max(25, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )

    if check.gripper_cx is not None:
        cv2.line(img, (int(check.gripper_cx), 0), (int(check.gripper_cx), h), (255, 0, 0), 2)
    if check.object_cx is not None:
        cv2.line(img, (int(check.object_cx), 0), (int(check.object_cx), h), (0, 255, 0), 2)

    cv2.putText(
        img,
        f"ALIGN: {'YES' if check.aligned else 'NO'} | MOVE {check.suggestion.upper()} | offset={check.offset_px}px",
        (20, max(35, h - 25)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.70,
        (0, 255, 0) if check.aligned else (0, 0, 255),
        2,
    )

    cv2.imwrite(str(output_path), img)
    return str(output_path)

