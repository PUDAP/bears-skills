---
name: colour-mixing-image-processing
description: Deterministic inner-well ROI extraction and RGB measurement for the fixed BEARS OT-2 camera.
---

# Image Processing

**Script**: [../../scripts/optimization_workflow/image_processing.py](../../scripts/optimization_workflow/image_processing.py)  
**Dependencies**: `numpy`, `Pillow`

## Design

The BEARS camera is fixed above the OT-2 deck and streams at `1920 × 1080`. The default colour-mixing plate is in slot 5. **Recalibrate geometry independently from every image capture.** A calibration is valid only for the exact image bytes from which its coordinates were measured. Never reuse a calibration, configuration, or coordinates for another capture, including another capture in the same optimization run.

The extraction path intentionally uses a small square patch at the centre of each well. The patch must remain inside the visible inner-well opening; it must not include the well wall, rim, or surrounding plate.

```text
run_pipeline(image_path, well_ids, config)
    │
    ├── Save perspective-corrected plate image
    ├── Interpolate 96 centres from A1, A12, H12, H1
    ├── Crop one centred 8×8 raw-pixel patch per well
    ├── Compute arithmetic-mean RGB for every patch
    ├── Save exact ROI alignment on the raw image
    ├── Save A1→H12 ROI-patch/RGB montage
    ├── Save all ROI coordinates and RGB values as CSV
    └── Return RGB values for the requested wells
```

## Orientation

A1 is the top-left well. Columns 1–12 run left to right and rows A–H run top to bottom:

```text
       1     2              12
A     A1    A2     ...     A12
B     B1    B2     ...     B12
...
H     H1    H2     ...     H12
```

## `ImageConfig`

| Field | Purpose |
|---|---|
| `src_corners` | Visible raw-image plate bounds `[TL, TR, BR, BL]`, used for the saved warped overview. |
| `dst_corners` | Destination bounds for the perspective-corrected overview. |
| `plate_width`, `plate_height` | Warped overview dimensions. |
| `col_num`, `row_num` | `12 × 8` for a 96-well plate. |
| `well_center_corners` | Raw-image centres `[A1, A12, H12, H1]`; source of truth for ROI extraction. |
| `inner_roi_size` | Side length of each centred square patch in raw pixels. Default: `8`. |
| `offset_array` | Legacy warped-grid fallback used only when `well_center_corners=None`. |

### Forbidden default geometry

```python
DEFAULT_CONFIG = ImageConfig(
    src_corners=[(678, 436), (949, 436), (949, 618), (678, 618)],
    dst_corners=[(0, 0), (1800, 0), (1800, 1200), (0, 1200)],
    plate_width=1800,
    plate_height=1200,
    col_num=12,
    row_num=8,
    offset_array=[[54, 54], [54, 54]],
    well_center_corners=[(712, 459), (920, 460), (919, 592), (711, 592)],
    inner_roi_size=8,
)
```

These coordinates are retained only as a historical example and as a rejection sentinel. `DEFAULT_CONFIG` must never be used, copied, or treated as a base configuration for an optimization measurement. Fresh coordinates must be measured from every captured image.

## Well-centre interpolation

`interpolate_well_centers()` takes the four corner-well centres in this exact order:

1. A1 — top-left
2. A12 — top-right
3. H12 — bottom-right
4. H1 — bottom-left

It uses bilinear interpolation to calculate all 96 centres while preserving perspective skew. Returned order is row-major: A1, A2, …, A12, B1, …, H12.

## Inner-well ROI extraction

`slice_inner_well_patches()` creates a centred square patch at every interpolated well centre.

Default patch size: `8 × 8` raw pixels.

The patch size is deliberately smaller than the visible inner-well diameter. Do not increase it merely to make the montage look larger; the montage enlarges patches for display using nearest-neighbour scaling. If the extraction box touches the rim or plate surface, reduce `inner_roi_size` or recalibrate `well_center_corners`.

The function fails when:

- the patch size is zero or negative;
- the corner-centre list does not contain exactly four points;
- any ROI falls outside the raw image;
- grid dimensions are invalid.

The older warped-grid `slice_roi_patches()` path remains available for custom configurations that explicitly set `well_center_corners=None`.

## RGB calculation

`mean_rgb()` calculates the arithmetic mean of every raw pixel in the inner-well patch:

```python
(R, G, B) = round(mean(patch_pixels, axis=(height, width)))
```

The result therefore corresponds exactly to the displayed patch and CSV coordinates. Median RGB is no longer used by the default colour-mixing flow.

## Artifacts

For an input named `<name>.jpg`, `run_pipeline()` saves:

| Artifact | Contents |
|---|---|
| `<name>_warped.jpg` | Perspective-corrected plate overview. |
| `<name>_roi_debug.jpg` | Exact inner-well ROI boxes on the raw image; corner labels establish orientation. |
| `<name>_roi_patches.png` | All 96 enlarged patches with well IDs and mean RGB values. |
| `<name>_rgb.csv` | Well ID, coordinate space (`raw` or legacy `warped`), half-open bounds (`x1`, `y1`, `x2_exclusive`, `y2_exclusive`), and mean R/G/B values. |

Custom paths can be supplied through `warped_save_path`, `roi_debug_save_path`, `roi_montage_save_path`, and `rgb_csv_save_path`.

## Usage

```python
from scripts.optimization_workflow.image_processing import (
    create_capture_calibration,
    run_pipeline,
)

capture_config = create_capture_calibration(
    capture_id="colour-run-001-capture-001",
    calibration_image_path="colour-RGB-sample-1.jpg",
    raw_image_size=(1920, 1080),
    src_corners=[<fresh TL>, <fresh TR>, <fresh BR>, <fresh BL>],
    well_center_corners=[<fresh A1>, <fresh A12>, <fresh H12>, <fresh H1>],
)

rgb_values = run_pipeline(
    image_path="colour-RGB-sample-1.jpg",
    well_ids=["A1", "A2", "A3"],
    config=capture_config,
    calibration_capture_id="colour-run-001-capture-001",
)
```

The returned dictionary contains only requested wells, while the montage and CSV contain all 96 wells.

## Mandatory per-capture recalibration procedure

1. Capture a fresh full-resolution image with the pipette arm clear and assign a unique capture ID.
2. Confirm the slot-5 plate and all 96 wells are visible.
3. Establish orientation with A1 at top-left.
4. Record the centre pixels of A1, A12, H12, and H1.
5. Set `well_center_corners` in that exact order.
6. Choose an `inner_roi_size` that remains fully inside the smallest visible well opening; use `8` for the current BEARS setup.
7. Record the visible outer plate bounds as `src_corners` for the warped overview.
8. Create the configuration with `create_capture_calibration(...)`, using the unique capture ID and the exact captured image path. The helper binds the configuration to the image path and SHA-256 hash.
9. Run `run_pipeline()` on that same image with the same ID as `calibration_capture_id`, then inspect both `_roi_debug` and `_roi_patches`.
10. Reject the capture if any sampling box touches a rim, lies between wells, or maps A1 anywhere except top-left.
11. Discard the configuration immediately after processing that capture.
12. Repeat the complete procedure from the next captured image, even within the same optimization run and even when framing appears unchanged.

Completion criterion: all 96 boxes are centred inside their wells, each patch is the configured size, and the CSV contains exactly A1 through H12.

## Validation

`validate_results()` checks:

- every RGB channel is within `0–255`;
- when multiple active wells are requested, at least one channel has the configured minimum inter-well spread.

The image-processing tests additionally verify:

- bilinear centre ordering from A1 to H12;
- exactly 96 patches;
- exact `8 × 8` patch dimensions;
- patches remain inside synthetic inner-well regions;
- RGB uses arithmetic mean rather than median;
- warped, debug, montage, and CSV artifacts are produced.

## Rules

- A request to **conduct image processing and ROI extraction** always starts with a new full-resolution camera capture followed by recalibration from that new image. Do not substitute the latest saved image or previously documented coordinates unless the user explicitly requests offline reprocessing.
- Every target, `x_init`, and optimization-iteration image must be recalibrated independently from that exact capture.
- Use a fresh image for each optimization measurement.
- Keep A1 at top-left; never silently rotate or mirror the mapping.
- Sample the raw image, not an enhanced or contrast-adjusted copy.
- Keep every ROI completely inside the well opening.
- Calculate RGB from the same pixels saved as the ROI patch.
- Inspect `_roi_debug.jpg` and `_roi_patches.png` before trusting changed calibration.
- Recalibrate before every capture, even within the same run and even when framing appears unchanged.
- Never use `DEFAULT_CONFIG`, copy its geometry, or reuse any earlier capture's `ImageConfig` or coordinates.
- Reject image processing when `calibration_capture_id` is missing, does not match the configuration, or the image path/hash differs from the calibrated capture.
- Reject the obsolete `calibration_run_id` interface; run-scoped calibration reuse is prohibited.
