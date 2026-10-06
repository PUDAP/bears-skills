---
name: colour-mixing-image-processing
description: Deterministic inner-well ROI extraction and RGB measurement for the fixed BEARS OT-2 camera.
---

# Image Processing

**Script**: [../../scripts/optimization_workflow/image_processing.py](../../scripts/optimization_workflow/image_processing.py)  
**Dependencies**: `numpy`, `Pillow`

## Design

The BEARS camera is fixed above the OT-2 deck and streams at `1920 × 1080`. The default colour-mixing plate is in slot 5. **Capture a fresh calibration image and recalibrate geometry before every colour-mixing optimization run.** Reuse that calibration only for images within the same optimization run; never carry it into a later run.

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

### BEARS default calibration

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

These coordinates are fallback examples from a `1920 × 1080` BEARS deck image with the wellplate in slot 5. They do not satisfy the per-run calibration requirement and must not be passed directly to an optimization measurement.

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
    create_run_calibration,
    run_pipeline,
)

run_config = create_run_calibration(
    run_id="colour-run-001",
    calibration_image_path="colour-run-001-calibration.jpg",
    raw_image_size=(1920, 1080),
    src_corners=[(678, 436), (949, 436), (949, 618), (678, 618)],
    well_center_corners=[(712, 459), (920, 460), (919, 592), (711, 592)],
)

rgb_values = run_pipeline(
    image_path="colour-RGB-sample-1.jpg",
    well_ids=["A1", "A2", "A3"],
    config=run_config,
    calibration_run_id="colour-run-001",
)
```

The returned dictionary contains only requested wells, while the montage and CSV contain all 96 wells.

## Mandatory per-run recalibration procedure

1. Capture a fresh full-resolution image with the pipette arm clear.
2. Confirm the slot-5 plate and all 96 wells are visible.
3. Establish orientation with A1 at top-left.
4. Record the centre pixels of A1, A12, H12, and H1.
5. Set `well_center_corners` in that exact order.
6. Choose an `inner_roi_size` that remains fully inside the smallest visible well opening; use `8` for the current BEARS setup.
7. Record the visible outer plate bounds as `src_corners` for the warped overview.
8. Run `run_pipeline()` and inspect both `_roi_debug` and `_roi_patches`.
9. Reject the calibration if any sampling box touches a rim, lies between wells, or maps A1 anywhere except top-left.
10. Create the configuration with `create_run_calibration(...)`, using the current optimization run ID and calibration-image path.
11. Pass the same run ID as `calibration_run_id` to every `run_pipeline(...)` call in that optimization run.
12. At the start of the next optimization run, discard this run configuration and repeat the procedure from a new image.

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
- Every optimization workflow must capture a new calibration image and recalibrate before its first image measurement, including RSI workflows.
- Use a fresh image for each optimization measurement.
- Keep A1 at top-left; never silently rotate or mirror the mapping.
- Sample the raw image, not an enhanced or contrast-adjusted copy.
- Keep every ROI completely inside the well opening.
- Calculate RGB from the same pixels saved as the ROI patch.
- Inspect `_roi_debug.jpg` and `_roi_patches.png` before trusting changed calibration.
- Recalibrate before every colour-mixing optimization run, even when framing appears unchanged.
- Never use `DEFAULT_CONFIG` directly for optimization measurements; it is a coordinate example/base configuration only.
- Reject image processing when `calibration_run_id` is missing, stale, or does not match the current optimization run.
