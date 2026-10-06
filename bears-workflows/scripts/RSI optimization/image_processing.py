"""
Image processing pipeline for colour mixing experiments.

Every captured image must be calibrated independently. Camera mounting and deck
geometry may be stable, but a previous image's coordinates and DEFAULT_CONFIG
must never be reused for an optimization measurement.

Pipeline (applied to every captured image):
    Step 1 — Compute 8 perspective coefficients from src_corners → plate rectangle.
    Step 2 — Apply PIL Image.PERSPECTIVE → flat, undistorted wellplate image.
    Step 3 — Bilinearly interpolate all 96 well centres from A1/A12/H12/H1.
    Step 4 — Extract a small square ROI patch fully inside each well opening.
    Step 5 — Save raw-image ROI debug and a labelled 96-patch RGB montage.
    Step 6 — Extract arithmetic-mean RGB for each requested well by ID.

Standard 96-well plate orientation:
    - Columns 1–12 run left → right in the image.
    - Rows A–H run top → bottom in the image.
    So well A1 is top-left and H12 is bottom-right.

Dependencies:
    pip install numpy Pillow
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Image configuration dataclass
# ---------------------------------------------------------------------------

@dataclass
class ImageConfig:
    """
    Geometric parameters calibrated from one exact captured image.

    Perspective correction:
        src_corners:  Four wellplate corners in the RAW image, ordered
                      [TL, TR, BR, BL], each as (x, y) in pixels.
                      Measure these from the raw captured photo.
        dst_corners:  Corresponding destination rectangle in the OUTPUT image,
                      ordered [TL, TR, BR, BL]. Typically starts at (0, 0)
                      and spans the full plate_width × plate_height area.
        plate_width:  Width in pixels of the warped output image.
        plate_height: Height in pixels of the warped output image.

    ROI extraction:
        col_num:      Columns in the grid. 12 for a 96-well plate (cols 1–12).
        row_num:      Rows in the grid. 8 for a 96-well plate (rows A–H).
        offset_array: Legacy warped-grid inset used only when
                      well_center_corners is not configured.
        well_center_corners:
                      Raw-image centres of [A1, A12, H12, H1]. The pipeline
                      bilinearly interpolates the other 92 well centres.
        inner_roi_size:
                      Side length in raw-image pixels for each centred square
                      ROI. Keep this smaller than the visible inner-well
                      diameter so the patch never includes the rim or plate.
    """
    src_corners: list[tuple[int, int]]
    dst_corners: list[tuple[int, int]]
    plate_width: int
    plate_height: int
    col_num: int
    row_num: int
    offset_array: list[list[int]]
    well_center_corners: list[tuple[float, float]] | None = None
    inner_roi_size: int = 8
    calibration_run_id: str | None = None
    calibration_image_path: str | None = None
    calibration_image_sha256: str | None = None
    calibration_scope: str | None = None
    calibrated_at_utc: str | None = None

    @property
    def output_size(self) -> tuple[int, int]:
        """(width, height) of the PIL perspective transform output."""
        return (self.plate_width, self.plate_height)


# Default calibration for the BEARS OT-2 slot-5 camera rig at 1920×1080.
# src_corners are the visible plate bounds; well_center_corners are the centres
# of A1, A12, H12, and H1 in that same raw image.
DEFAULT_CONFIG = ImageConfig(
    src_corners=[(678, 436), (949, 436), (949, 618), (678, 618)],
    dst_corners=[(0, 0), (1800, 0), (1800, 1200), (0, 1200)],
    plate_width=1800,
    plate_height=1200,
    col_num=12,    # columns 1–12, left → right
    row_num=8,     # rows A–H, top → bottom
    offset_array=[[54, 54], [54, 54]],  # legacy warped-grid fallback
    well_center_corners=[(712, 459), (920, 460), (919, 592), (711, 592)],
    inner_roi_size=8,
)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_capture_calibration(
    *,
    capture_id: str,
    calibration_image_path: str,
    raw_image_size: tuple[int, int],
    src_corners: list[tuple[int, int]],
    well_center_corners: list[tuple[float, float]],
    inner_roi_size: int | None = None,
) -> ImageConfig:
    """Create geometry valid only for one exact captured image.

    ``src_corners`` must be ``[TL, TR, BR, BL]`` and
    ``well_center_corners`` must be ``[A1, A12, H12, H1]`` from the current
    captured image. The image path and SHA-256 are stamped into the config so
    reuse on another image is rejected, even within the same campaign.
    """
    if not isinstance(capture_id, str) or not capture_id.strip():
        raise ValueError("capture_id must be a non-empty string.")
    if not isinstance(calibration_image_path, str) or not calibration_image_path.strip():
        raise ValueError("calibration_image_path must identify the fresh calibration image.")
    calibration_image_path = os.path.abspath(calibration_image_path)
    if not os.path.isfile(calibration_image_path):
        raise ValueError("calibration_image_path must exist and identify the current capture.")
    width, height = raw_image_size
    if width <= 0 or height <= 0:
        raise ValueError("raw_image_size must contain positive width and height.")
    if len(src_corners) != 4:
        raise ValueError("src_corners must contain [TL, TR, BR, BL].")
    if len(well_center_corners) != 4:
        raise ValueError("well_center_corners must contain [A1, A12, H12, H1].")
    if (
        list(src_corners) == DEFAULT_CONFIG.src_corners
        and list(well_center_corners) == DEFAULT_CONFIG.well_center_corners
    ):
        raise ValueError(
            "DEFAULT_CONFIG geometry is a documentation example and cannot be used "
            "for an optimization measurement; recalibrate from the current capture."
        )

    all_points = [*src_corners, *well_center_corners]
    for index, point in enumerate(all_points):
        if len(point) != 2 or any(not math.isfinite(float(value)) for value in point):
            raise ValueError(f"Calibration point {index} must contain two finite coordinates.")
        x, y = float(point[0]), float(point[1])
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(
                f"Calibration point {index} ({x}, {y}) is outside {width}x{height}."
            )

    tl, tr, br, bl = src_corners
    a1, a12, h12, h1 = well_center_corners
    if not (tl[0] < tr[0] and bl[0] < br[0] and tl[1] < bl[1] and tr[1] < br[1]):
        raise ValueError("src_corners orientation must be TL, TR, BR, BL.")
    if not (a1[0] < a12[0] and h1[0] < h12[0] and a1[1] < h1[1] and a12[1] < h12[1]):
        raise ValueError("well_center_corners orientation must be A1, A12, H12, H1.")

    with Image.open(calibration_image_path) as image:
        if image.size != (width, height):
            raise ValueError(
                f"raw_image_size {(width, height)} does not match current capture {image.size}."
            )

    roi_size = 8 if inner_roi_size is None else inner_roi_size
    if roi_size <= 0:
        raise ValueError("inner_roi_size must be positive.")
    return ImageConfig(
        src_corners=[(int(x), int(y)) for x, y in src_corners],
        dst_corners=[(0, 0), (1800, 0), (1800, 1200), (0, 1200)],
        plate_width=1800,
        plate_height=1200,
        col_num=12,
        row_num=8,
        offset_array=[[54, 54], [54, 54]],
        well_center_corners=[(float(x), float(y)) for x, y in well_center_corners],
        inner_roi_size=roi_size,
        calibration_run_id=capture_id.strip(),
        calibration_image_path=calibration_image_path,
        calibration_image_sha256=_sha256_file(calibration_image_path),
        calibration_scope="capture",
        calibrated_at_utc=datetime.now(timezone.utc).isoformat(),
    )


def create_run_calibration(**kwargs) -> ImageConfig:
    """Reject the obsolete run-scoped calibration API."""
    raise RuntimeError(
        "Run-scoped calibration reuse is prohibited. Use create_capture_calibration() "
        "with a unique capture_id and geometry measured from the current image."
    )


def validate_capture_calibration(
    config: ImageConfig,
    expected_capture_id: str,
    image_path: str,
) -> None:
    """Reject missing, default, stale, or cross-image calibration."""
    if not expected_capture_id:
        raise ValueError("expected_capture_id must be non-empty.")
    if config is DEFAULT_CONFIG or config.calibration_scope != "capture":
        raise ValueError(
            "A fresh capture-scoped calibration is required; DEFAULT_CONFIG and "
            "run-scoped configurations are not valid for optimization measurements."
        )
    if config.calibration_run_id != expected_capture_id:
        raise ValueError(
            "Image calibration is missing or belongs to another capture: "
            f"expected {expected_capture_id!r}, got {config.calibration_run_id!r}."
        )
    current_path = os.path.abspath(image_path)
    if config.calibration_image_path != current_path:
        raise ValueError(
            "Calibration image does not match the image being processed; recalibrate "
            "src_corners and well_center_corners from the current capture."
        )
    if (
        not config.calibration_image_sha256
        or config.calibration_image_sha256 != _sha256_file(current_path)
    ):
        raise ValueError("Current capture hash differs from the calibrated image.")
    if not config.calibrated_at_utc:
        raise ValueError("Capture calibration provenance is incomplete.")
    if (
        config.src_corners == DEFAULT_CONFIG.src_corners
        and config.well_center_corners == DEFAULT_CONFIG.well_center_corners
    ):
        raise ValueError("DEFAULT_CONFIG geometry cannot be used for optimization measurements.")


def validate_run_calibration(config: ImageConfig, expected_run_id: str) -> None:
    """Reject the obsolete validation path before it can permit reuse."""
    raise RuntimeError(
        "Run-scoped calibration reuse is prohibited. Validate the exact image with "
        "validate_capture_calibration(config, capture_id, image_path)."
    )


# ---------------------------------------------------------------------------
# Perspective correction (PIL-based)
# ---------------------------------------------------------------------------

def find_coeffs(
    pa: list[tuple[int, int]],
    pb: list[tuple[int, int]],
) -> list[float]:
    """
    Compute 8 perspective transformation coefficients for PIL Image.PERSPECTIVE.

    Solves the 8×8 linear system that maps source points (pb, raw image) to
    destination points (pa, flat output). Pass the result directly to
    img.transform(..., Image.PERSPECTIVE, coeffs, Image.BICUBIC).

    Args:
        pa: Four points in the OUTPUT image (destination rectangle).
        pb: Four corresponding points in the INPUT image (wellplate corners).

    Returns:
        List of 8 floats for PIL img.transform().
    """
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0] * p1[0], -p2[0] * p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1] * p1[0], -p2[1] * p1[1]])
    A = np.array(matrix, dtype=np.float64)
    B = np.array(pb, dtype=np.float64).reshape(8)
    return np.linalg.solve(A, B).tolist()


# ---------------------------------------------------------------------------
# Grid dimensions
# ---------------------------------------------------------------------------

def get_grid_dimensions(
    plate_np: np.ndarray,
    col_num: int,
    row_num: int,
) -> tuple[float, float]:
    """
    Compute the pixel dimensions of one grid cell in the plate image.

    After warping (and optional crop), the plate image is divided into
    row_num × col_num equal cells. This function returns the floating-point
    width and height of each cell.

    Args:
        plate_np: Flat plate image (after warp + optional crop) as NumPy array.
        col_num:  Number of columns in the grid (e.g. 12).
        row_num:  Number of rows in the grid (e.g. 8).

    Returns:
        (cell_w, cell_h) — pixel dimensions of one grid cell (float).
    """
    h, w = plate_np.shape[:2]
    return w / col_num, h / row_num


def _validate_roi_box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    well_label: str,
) -> None:
    """Fail fast when ROI padding would produce an empty or inverted crop."""
    if x1 >= x2 or y1 >= y2:
        raise ValueError(
            f"Invalid ROI for {well_label}: box ({x1}, {y1}, {x2}, {y2}) is empty. "
            "Check offset_array, crop_box, and output geometry."
        )


# ---------------------------------------------------------------------------
# ROI grid slicing
# ---------------------------------------------------------------------------

def slice_roi_patches(
    plate_np: np.ndarray,
    col_num: int,
    row_num: int,
    offset_array: list[list[int]],
) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
    """
    Divide the flat plate image into a grid and extract one ROI patch per well.

    Each grid cell is shrunk inward by offset_array to avoid the well rim.
    Patches are returned in row-major order: A1, A2, …, A12, B1, B2, …, H12.

    Args:
        plate_np:     Flat plate image (after warp + optional crop), (H, W, 3).
        col_num:      Number of grid columns (12 for cols 1–12).
        row_num:      Number of grid rows (8 for rows A–H).
        offset_array: [[x_pad_left, x_pad_right], [y_pad_top, y_pad_bottom]].

    Returns:
        patches:   List of ROI arrays in row-major order (96 items for 96-well).
        roi_boxes: List of (x1, y1, x2, y2) for each patch — used by the debug image.
    """
    cell_w, cell_h = get_grid_dimensions(plate_np, col_num, row_num)
    x_pad_l, x_pad_r = offset_array[0]
    y_pad_t, y_pad_b = offset_array[1]

    patches: list[np.ndarray] = []
    roi_boxes: list[tuple[int, int, int, int]] = []

    for row in range(row_num):
        for col in range(col_num):
            x1 = int(cell_w * col) + x_pad_l
            x2 = int(cell_w * (col + 1)) - x_pad_r
            y1 = int(cell_h * row) + y_pad_t
            y2 = int(cell_h * (row + 1)) - y_pad_b
            well_id = f"{chr(ord('A') + row)}{col + 1}"
            _validate_roi_box(x1, y1, x2, y2, well_id)
            patches.append(plate_np[y1:y2, x1:x2])
            roi_boxes.append((x1, y1, x2, y2))

    return patches, roi_boxes


def interpolate_well_centers(
    corner_centers: list[tuple[float, float]],
    col_num: int,
    row_num: int,
) -> list[tuple[float, float]]:
    """Interpolate row-major well centres from [A1, A12, H12, H1]."""
    if len(corner_centers) != 4:
        raise ValueError("corner_centers must contain [A1, A12, H12, H1].")
    if col_num < 2 or row_num < 2:
        raise ValueError("col_num and row_num must both be at least 2.")

    top_left, top_right, bottom_right, bottom_left = corner_centers
    centers: list[tuple[float, float]] = []
    for row in range(row_num):
        v = row / (row_num - 1)
        for col in range(col_num):
            u = col / (col_num - 1)
            x = (
                (1 - u) * (1 - v) * top_left[0]
                + u * (1 - v) * top_right[0]
                + u * v * bottom_right[0]
                + (1 - u) * v * bottom_left[0]
            )
            y = (
                (1 - u) * (1 - v) * top_left[1]
                + u * (1 - v) * top_right[1]
                + u * v * bottom_right[1]
                + (1 - u) * v * bottom_left[1]
            )
            centers.append((x, y))
    return centers


def slice_inner_well_patches(
    raw_np: np.ndarray,
    corner_centers: list[tuple[float, float]],
    col_num: int,
    row_num: int,
    roi_size: int,
) -> tuple[list[np.ndarray], list[tuple[int, int, int, int]]]:
    """Extract centred square patches that remain inside each well opening."""
    if roi_size <= 0:
        raise ValueError("roi_size must be positive.")

    image_h, image_w = raw_np.shape[:2]
    patches: list[np.ndarray] = []
    roi_boxes: list[tuple[int, int, int, int]] = []
    for idx, (center_x, center_y) in enumerate(
        interpolate_well_centers(corner_centers, col_num, row_num)
    ):
        row, col = divmod(idx, col_num)
        well_id = f"{chr(ord('A') + row)}{col + 1}"
        x1 = int(round(center_x - roi_size / 2))
        y1 = int(round(center_y - roi_size / 2))
        x2 = x1 + roi_size
        y2 = y1 + roi_size
        _validate_roi_box(x1, y1, x2, y2, well_id)
        if x1 < 0 or y1 < 0 or x2 > image_w or y2 > image_h:
            raise ValueError(
                f"Inner ROI for {well_id} falls outside the raw image: "
                f"({x1}, {y1}, {x2}, {y2}) vs {image_w}×{image_h}."
            )
        patches.append(raw_np[y1:y2, x1:x2])
        roi_boxes.append((x1, y1, x2, y2))

    return patches, roi_boxes


# ---------------------------------------------------------------------------
# Well slot mapping and single-well crop
# ---------------------------------------------------------------------------

def well_to_grid_pos(well_id: str) -> tuple[int, int]:
    """
    Convert a well identifier to its (image_row, image_col) grid position.

    Standard orientation — columns 1–12 run left→right, rows A–H run top→bottom:
        A1  → (row=0, col=0)   top-left
        A12 → (row=0, col=11)  top-right
        H1  → (row=7, col=0)   bottom-left
        H12 → (row=7, col=11)  bottom-right

    Args:
        well_id: Well identifier, e.g. "A1", "B3", "H12".

    Returns:
        (image_row, image_col) zero-based grid indices.

    Raises:
        ValueError: If the format is invalid.
    """
    if len(well_id) < 2 or not well_id[0].isalpha() or not well_id[1:].isdigit():
        raise ValueError(f"Invalid well_id '{well_id}'. Expected format e.g. 'A1'.")
    image_row = ord(well_id[0].upper()) - ord('A')   # A→0 … H→7
    image_col = int(well_id[1:]) - 1                 # 1→0 … 12→11
    return image_row, image_col


def _validate_well_in_bounds(
    well_id: str,
    image_row: int,
    image_col: int,
    col_num: int,
    row_num: int,
) -> None:
    """Validate that a parsed well lies within the configured plate grid."""
    if not (0 <= image_row < row_num):
        last_row = chr(ord("A") + row_num - 1)
        raise ValueError(
            f"Invalid well_id '{well_id}'. Row must be between A and {last_row}."
        )
    if not (0 <= image_col < col_num):
        raise ValueError(
            f"Invalid well_id '{well_id}'. Column must be between 1 and {col_num}."
        )


def well_to_roi_index(well_id: str, col_num: int, row_num: int = 8) -> int:
    """
    Convert a well identifier to its flat index in the patches list.

    Patches are stored in row-major order (A1=0, A2=1, …, A12=11, B1=12, …).

    Args:
        well_id:  Well identifier, e.g. "A1", "B3", "H12".
        col_num:  Number of grid columns (12 for a 96-well plate).
        row_num:  Number of grid rows (8 for a 96-well plate). Default: 8.

    Returns:
        Integer index into the patches list from slice_roi_patches().
    """
    image_row, image_col = well_to_grid_pos(well_id)
    _validate_well_in_bounds(well_id, image_row, image_col, col_num, row_num)
    return image_row * col_num + image_col


def crop_well(
    plate_np: np.ndarray,
    well_id: str,
    col_num: int,
    row_num: int,
    offset_array: list[list[int]],
) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """
    Crop a single named well from the flat plate image.

    Computes the well's pixel bounding box from the grid dimensions, applies
    the offset_array inset, and returns the patch array and its box.

    Args:
        plate_np:     Flat plate image (after warp + optional crop), (H, W, 3).
        well_id:      Well identifier, e.g. "A1", "B3", "H12".
        col_num:      Number of grid columns (12).
        row_num:      Number of grid rows (8).
        offset_array: [[x_pad_left, x_pad_right], [y_pad_top, y_pad_bottom]].

    Returns:
        (patch, (x1, y1, x2, y2)) — the well's ROI array and its bounding box
        in plate_np coordinates.
    """
    cell_w, cell_h = get_grid_dimensions(plate_np, col_num, row_num)
    image_row, image_col = well_to_grid_pos(well_id)
    _validate_well_in_bounds(well_id, image_row, image_col, col_num, row_num)

    x_pad_l, x_pad_r = offset_array[0]
    y_pad_t, y_pad_b = offset_array[1]

    x1 = int(cell_w * image_col) + x_pad_l
    x2 = int(cell_w * (image_col + 1)) - x_pad_r
    y1 = int(cell_h * image_row) + y_pad_t
    y2 = int(cell_h * (image_row + 1)) - y_pad_b
    _validate_roi_box(x1, y1, x2, y2, well_id)

    return plate_np[y1:y2, x1:x2], (x1, y1, x2, y2)


# ---------------------------------------------------------------------------
# ROI debug visualisation
# ---------------------------------------------------------------------------

def save_roi_debug_image(
    plate_np: np.ndarray,
    roi_boxes: list[tuple[int, int, int, int]],
    save_path: str,
    col_num: int,
    row_num: int,
    outline_colour: tuple[int, int, int] = (220, 30, 30),
    outline_width: int = 2,
    font_size: int = 9,
) -> str:
    """
    Draw red rectangles over every ROI patch on the flat plate image and label
    each with its pixel dimensions (W×H) and well ID (e.g. A1).

    Args:
        plate_np:      Flat plate image as NumPy array (H, W, 3) in RGB.
        roi_boxes:     List of (x1, y1, x2, y2) from slice_roi_patches().
        save_path:     File path to save the annotated image.
        col_num:       Number of grid columns (needed to derive well IDs).
        row_num:       Number of grid rows (needed to derive well IDs).
        outline_colour: RGB colour of the rectangle outlines. Default: red.
        outline_width: Border thickness in pixels.
        font_size:     Font size for labels.

    Returns:
        save_path, so the caller can log it.
    """
    debug_pil = Image.fromarray(plate_np.astype(np.uint8))
    draw = ImageDraw.Draw(debug_pil)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    for idx, (x1, y1, x2, y2) in enumerate(roi_boxes):
        row_idx = idx // col_num
        col_idx = idx % col_num
        well_id = f"{chr(ord('A') + row_idx)}{col_idx + 1}"
        patch_w, patch_h = x2 - x1, y2 - y1
        label = f"{well_id} {patch_w}×{patch_h}"

        draw.rectangle(
            [x1, y1, x2 - 1, y2 - 1],
            outline=outline_colour,
            width=outline_width,
        )
        draw.text((x1 + 1, y1 + 1), label, fill=outline_colour, font=font)

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    save_pil_image(debug_pil, save_path)
    return save_path


def save_inner_roi_debug_image(
    raw_np: np.ndarray,
    roi_boxes: list[tuple[int, int, int, int]],
    save_path: str,
    col_num: int,
    row_num: int,
    outline_colour: tuple[int, int, int] = (0, 255, 255),
) -> str:
    """Draw the exact inner-well sampling boxes on the unwarped raw image."""
    debug_pil = Image.fromarray(raw_np.astype(np.uint8))
    draw = ImageDraw.Draw(debug_pil)
    for x1, y1, x2, y2 in roi_boxes:
        draw.rectangle([x1, y1, x2 - 1, y2 - 1], outline=outline_colour, width=1)

    last_row = chr(ord("A") + row_num - 1)
    corner_indices = {
        0: "A1",
        col_num - 1: f"A{col_num}",
        len(roi_boxes) - col_num: f"{last_row}1",
        len(roi_boxes) - 1: f"{last_row}{col_num}",
    }
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 13)
    except (OSError, IOError):
        font = ImageFont.load_default()
    for idx, label in corner_indices.items():
        x1, y1, x2, y2 = roi_boxes[idx]
        draw.text(
            (x1, y1 - 16 if idx < col_num else y2 + 2),
            label,
            fill=(255, 255, 0),
            font=font,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    save_pil_image(debug_pil, save_path)
    return save_path


def save_roi_patch_montage(
    patches: list[np.ndarray],
    rgb_values: dict[str, tuple[int, int, int]],
    save_path: str,
    col_num: int,
    row_num: int,
) -> str:
    """Save an A1→H12 montage with each inner patch and mean RGB value."""
    expected = col_num * row_num
    if len(patches) != expected:
        raise ValueError(f"Expected {expected} patches, got {len(patches)}.")

    tile_w, tile_h = 118, 118
    margin, header = 20, 65
    montage = Image.new(
        "RGB",
        (margin * 2 + col_num * tile_w, header + margin + row_num * tile_h),
        (246, 248, 251),
    )
    draw = ImageDraw.Draw(montage)
    try:
        bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 13)
        text = ImageFont.truetype("DejaVuSans.ttf", 11)
        tiny = ImageFont.truetype("DejaVuSans-Bold.ttf", 10)
    except (OSError, IOError):
        bold = text = tiny = ImageFont.load_default()

    draw.text((margin, 10), "Inner-well ROI patches and mean RGB", fill=(20, 25, 35), font=bold)
    draw.text(
        (margin, 32),
        "A1 top-left; each patch remains inside the well opening",
        fill=(65, 75, 90),
        font=text,
    )
    for idx, patch in enumerate(patches):
        row, col = divmod(idx, col_num)
        well_id = f"{chr(ord('A') + row)}{col + 1}"
        base_x, base_y = margin + col * tile_w, header + row * tile_h
        patch_image = Image.fromarray(patch.astype(np.uint8)).resize(
            (72, 72), Image.Resampling.NEAREST
        )
        x, y = base_x + 23, base_y + 18
        montage.paste(patch_image, (x, y))
        draw.rectangle((x - 1, y - 1, x + 72, y + 72), outline=(55, 65, 80), width=1)
        draw.text((base_x + 48, base_y + 3), well_id, fill=(20, 25, 35), font=tiny)
        rgb = rgb_values[well_id]
        rgb_text = f"{rgb[0]},{rgb[1]},{rgb[2]}"
        draw.text((base_x + 31, base_y + 93), rgb_text, fill=(20, 25, 35), font=text)
        draw.rectangle(
            (base_x + 49, base_y + 108, base_x + 69, base_y + 115),
            fill=rgb,
            outline=(70, 70, 70),
        )

    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    save_pil_image(montage, save_path)
    return save_path


def save_rgb_csv(
    rgb_values: dict[str, tuple[int, int, int]],
    roi_boxes: list[tuple[int, int, int, int]],
    save_path: str,
    coordinate_space: str,
) -> str:
    """Save well RGB values with half-open ROI bounds and coordinate space."""
    if coordinate_space not in {"raw", "warped"}:
        raise ValueError("coordinate_space must be 'raw' or 'warped'.")
    if len(rgb_values) != len(roi_boxes):
        raise ValueError("rgb_values and roi_boxes must have the same length.")
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    with open(save_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "well",
                "coordinate_space",
                "x1",
                "y1",
                "x2_exclusive",
                "y2_exclusive",
                "mean_R",
                "mean_G",
                "mean_B",
            ]
        )
        for (well_id, rgb), (x1, y1, x2, y2) in zip(rgb_values.items(), roi_boxes):
            writer.writerow([well_id, coordinate_space, x1, y1, x2, y2, *rgb])
    return save_path


def save_pil_image(image: Image.Image, save_path: str) -> None:
    """
    Save an image with higher-quality settings for JPEG outputs.

    Perspective-corrected plate images and ROI debug images are often inspected
    visually, so avoid low-quality default JPEG settings that can make the
    warped image appear soft or blocky.
    """
    suffix = os.path.splitext(save_path)[1].lower()
    if suffix in {".jpg", ".jpeg"}:
        image.save(save_path, quality=95, subsampling=0, optimize=True)
    else:
        image.save(save_path)


# ---------------------------------------------------------------------------
# RGB extraction
# ---------------------------------------------------------------------------

def mean_rgb(patch: np.ndarray) -> tuple[int, int, int]:
    """
    Compute arithmetic-mean RGB for one inner-well ROI patch.

    The ROI geometry is responsible for excluding the well rim and surrounding
    plate. Averaging every raw pixel in that interior patch matches the saved
    patch montage and CSV values exactly.

    Args:
        patch: ROI patch as NumPy array (H, W, 3) in RGB.

    Returns:
        (R, G, B) arithmetic means rounded to integers 0–255.
    """
    if patch.size == 0:
        raise ValueError("Cannot compute RGB from an empty ROI patch.")
    channel_means = np.rint(np.mean(patch, axis=(0, 1))).astype(int)
    return int(channel_means[0]), int(channel_means[1]), int(channel_means[2])


def extract_well_rgb(
    patches: list[np.ndarray],
    well_ids: list[str],
    col_num: int,
) -> dict[str, tuple[int, int, int]]:
    """
    Extract the arithmetic-mean RGB value for each specified well.

    Args:
        patches:  Full list of ROI patches from slice_roi_patches() — all wells.
        well_ids: List of well identifiers, e.g. ["A1", "A2", "A3"].
        col_num:  Number of grid columns used during slicing (12).

    Returns:
        Dict mapping each well_id to its arithmetic-mean (R, G, B) tuple.
    """
    if col_num <= 0:
        raise ValueError("col_num must be positive.")
    if len(patches) % col_num != 0:
        raise ValueError(
            f"Expected patches length to be divisible by col_num, got "
            f"{len(patches)} patches for {col_num} columns."
        )

    row_num = len(patches) // col_num
    rgb_values: dict[str, tuple[int, int, int]] = {}
    for wid in well_ids:
        image_row, image_col = well_to_grid_pos(wid)
        _validate_well_in_bounds(wid, image_row, image_col, col_num, row_num)
        rgb_values[wid] = mean_rgb(patches[image_row * col_num + image_col])
    return rgb_values


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_results(
    rgb_values: dict[str, tuple[int, int, int]],
    min_colour_spread: int = 10,
) -> tuple[bool, list[str]]:
    """
    Validate that extracted RGB values are plausible.

    Checks:
        1. RGB range   — all channel values in 0–255.
        2. Colour spread — at least one channel varies by > min_colour_spread
                          across active wells (confirms mixes were dispensed).

    Args:
        rgb_values:        {well_id: (R, G, B)} from extract_well_rgb().
        min_colour_spread: Minimum inter-well channel range. Default: 10.

    Returns:
        (passed, failures) — passed is True when all checks pass.
    """
    failures: list[str] = []

    for wid, (r, g, b) in rgb_values.items():
        if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
            failures.append(f"Well {wid}: RGB ({r},{g},{b}) out of 0–255 range.")

    if len(rgb_values) > 1:
        per_channel = list(zip(*rgb_values.values()))
        for ch in per_channel:
            if (max(ch) - min(ch)) >= min_colour_spread:
                break
        else:
            failures.append(
                f"All active wells have nearly identical colours "
                f"(spread < {min_colour_spread} on every channel). "
                "Check that mixes were actually dispensed."
            )

    return len(failures) == 0, failures


# ---------------------------------------------------------------------------
# Full pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    image_path: str,
    well_ids: list[str],
    config: ImageConfig | None = None,
    warped_save_path: str | None = None,
    roi_debug_save_path: str | None = None,
    roi_montage_save_path: str | None = None,
    rgb_csv_save_path: str | None = None,
    calibration_capture_id: str | None = None,
    calibration_run_id: str | None = None,
) -> dict[str, tuple[int, int, int]]:
    """
    Run the full image processing pipeline for one captured image.

    Steps:
        1. Load the raw image and save a perspective-corrected plate view.
        2. Interpolate all well centres from calibrated A1/A12/H12/H1 centres.
        3. Extract one centred square patch fully inside each well opening.
        4. Save raw-image ROI alignment, patch montage, and RGB CSV artifacts.
        5. Compute arithmetic-mean RGB for every patch and select well_ids.
        6. Validate the requested RGB values.

    If well_center_corners is None, the legacy warped-grid ROI path remains
    available for older/custom ImageConfig instances.

    Saved files (paths auto-derived from image_path if not supplied):
        <name>_warped.jpg       — perspective-corrected plate image.
        <name>_roi_debug.jpg    — exact ROI boxes on the image used for sampling.
        <name>_roi_patches.png  — A1→H12 patch montage with mean RGB values.
        <name>_rgb.csv          — all 96 mean RGB values and ROI coordinates.

    Returns:
        {"A1": (R, G, B), "A2": (R, G, B), ...} for requested well_ids.
    """
    def ensure_parent_dir(path: str) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)

    base, ext = os.path.splitext(image_path)
    ext = ext or ".jpg"

    if calibration_run_id is not None:
        raise ValueError(
            "calibration_run_id is obsolete because one calibration cannot be reused "
            "across a run. Supply calibration_capture_id for this exact image."
        )
    if config is None or calibration_capture_id is None:
        raise ValueError(
            "run_pipeline requires a fresh capture-scoped config and "
            "calibration_capture_id for every image."
        )
    validate_capture_calibration(config, calibration_capture_id, image_path)

    raw_pil = Image.open(image_path).convert("RGB")
    raw_np = np.array(raw_pil)
    coeffs = find_coeffs(config.dst_corners, config.src_corners)
    warped_pil = raw_pil.transform(config.output_size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    warped_np = np.array(warped_pil)

    if warped_save_path is None:
        warped_save_path = f"{base}_warped{ext}"
    ensure_parent_dir(warped_save_path)
    save_pil_image(warped_pil, warped_save_path)

    if config.well_center_corners is not None:
        patches, roi_boxes = slice_inner_well_patches(
            raw_np,
            config.well_center_corners,
            config.col_num,
            config.row_num,
            config.inner_roi_size,
        )
        debug_np = raw_np
        coordinate_space = "raw"
    else:
        patches, roi_boxes = slice_roi_patches(
            warped_np, config.col_num, config.row_num, config.offset_array
        )
        debug_np = warped_np
        coordinate_space = "warped"

    all_well_ids = [
        f"{chr(ord('A') + row)}{col + 1}"
        for row in range(config.row_num)
        for col in range(config.col_num)
    ]
    all_rgb_values = extract_well_rgb(patches, all_well_ids, config.col_num)
    rgb_values = extract_well_rgb(patches, well_ids, config.col_num)

    if roi_debug_save_path is None:
        roi_debug_save_path = f"{base}_roi_debug{ext}"
    ensure_parent_dir(roi_debug_save_path)
    if config.well_center_corners is not None:
        save_inner_roi_debug_image(
            debug_np,
            roi_boxes,
            roi_debug_save_path,
            config.col_num,
            config.row_num,
        )
    else:
        save_roi_debug_image(
            debug_np,
            roi_boxes,
            roi_debug_save_path,
            config.col_num,
            config.row_num,
        )

    if roi_montage_save_path is None:
        roi_montage_save_path = f"{base}_roi_patches.png"
    save_roi_patch_montage(
        patches,
        all_rgb_values,
        roi_montage_save_path,
        config.col_num,
        config.row_num,
    )

    if rgb_csv_save_path is None:
        rgb_csv_save_path = f"{base}_rgb.csv"
    save_rgb_csv(all_rgb_values, roi_boxes, rgb_csv_save_path, coordinate_space)

    passed, failures = validate_results(rgb_values)
    if not passed:
        raise RuntimeError(
            f"RGB validation failed: {failures}. "
            f"Inspect {roi_debug_save_path} and {roi_montage_save_path}."
        )

    return rgb_values
