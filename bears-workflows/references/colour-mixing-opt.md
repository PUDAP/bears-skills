---
name: colour-mixing-opt
description: Iteratively mix RGB colours on an Opentrons OT-2 and minimize RMSE between the mixed colour and a target colour using real-time camera feedback and BO or LLM optimization.
---

# Colour Mixing Optimization

description: Iteratively mix RGB colours on an Opentrons OT-2 and minimize RMSE between the mixed colour and a target colour using real-time camera feedback and BO or LLM optimization.

## Required Skills

Invoke these skills before generating any commands:
- **puda-machines** → opentrons machine (liquid handling + `camera_capture`)
- **puda-protocol** → protocol generation and execution
- **puda-memory** → update `experiment.md` after every protocol creation and run

## Required Machine

- **Opentrons OT-2** with camera attached (`machine_id: "opentrons"`)

## Core Principle 
The system must operate in a strict single-run, sequential execution loop.
At any time:
- Only **One active run** is allowed 
- Each iteration sues a **NEW run_id**
-No downstream step executres unless the run is **confirmed successful**

## Optimization Approaches

Ask the user which approach to use if not specified:

| Approach | When to use |
|---|---|
| **Bayesian Optimization (BO)** | Efficient for continuous volume ratios; fewer iterations to converge |
| **LLM** | Flexible reasoning; good when constraints or colour theory context matters |

See [optimization.md](optimization.md) for implementation details.

---

## Workflow

### Phase 0 — Run Lifecycle Safety

This applies to every iteration.

Mandatory Rules
-Always create a new run per protocol
-Never reuse run_id
-Never send play twice on same run
-Never start a run if another run is active
-Always poll until run reaches terminal state: successded, failed or stopped 

Hard Gate Condition

Proceed ONLY IF:
run.status == "succeeded"

Otherwise:
-STOP optimization loop
-Log failure
-Require recovery before continuing

### Phase 1 — Initialization

**Step 1 — Inputs (ask user before proceeding)**

Collect all of the following before starting. Do not proceed until every value is confirmed:

| Input | Description |
|---|---|
| Sample name | User-provided sample name to use in saved image filenames |
| Target colour | `(R, G, B)` where each value is 0–255 |
| Total well volume | Total volume in µL per well (e.g. 300 µL) |
| **R dye source — deck slot** | OT-2 deck slot (`"1"`–`"11"`) for the labware holding **red** dye only |
| **G dye source — deck slot** | Deck slot for the labware holding **green** dye only |
| **B dye source — deck slot** | Deck slot for the labware holding **blue** dye only |
| `x_init` — 3 initial mixes | User-provided volume sets (see below) |
| Optimization approach | BO (EI or LCB) or LLM (choose model) |
| RMSE threshold | Stop when RMSE ≤ this value |
| Maximum iterations | Stop after this many iterations |

**Critical — RGB dye labware are three separate deck positions**

The R, G, and B dyes are loaded as **three independent `load_labware` calls** with **three separate `location` values**. You must **ask the user for each slot individually** (R, then G, then B — or present one form with three distinct fields). **Do not** ask a single question such as “which slot is the dye plate?” and reuse that answer for R, G, and B. **Do not** assume all three dye plates share the same slot.

When generating protocols, map aspirate sources to the user’s **R slot / G slot / B slot** explicitly — never copy one slot onto all three dye labware loads.

**`x_init` — Initial volume inputs**

Ask the user to provide exactly 3 initial volume combinations for R, G, B dye in µL. Each set must sum to the total well volume.
Validate each set before generating the protocol — reject and re-ask if any set does not sum to `total_volume` (±1 µL tolerance).

**Step 1a — User confirmation before execution**
After all inputs have been collected and validated, present a single summary back to the user that also states the labware positions, and ask for explicit confirmation before generating or executing any protocol.

The confirmation summary must include:
- Sample name
- Target colour
- Total well volume
- Labware positions
- R / G / B source deck slots
- All 3 `x_init` volume combinations
- Optimization approach
- RMSE threshold
- Maximum iterations


Do not generate the initial protocol until the user confirms that the full setup is correct.

**Step 2 — Initial mixes (`x_init`)**
Generate a single protocol that dispenses all 3 initial volume combinations into 3 separate wells (e.g. A1, A2, A3) and execute it on the Opentrons. Record which well received which `(R_vol, G_vol, B_vol)` set.

Tip usage must advance in row-major order on the tip rack:

```text
A1, A2, A3, ... A12, B1, B2, ... H12
```
**Execution Sequence (MUST FOLLOW EXACTLY)**
1. Upload protocol
2. Create run -> store `run_id`
3. Verify:
   - No active run
   - Robot not in error state
4. Start run (`play`)
5. Poll run status until terminal

**Step 3 — Capture whole-wellplate image**
After the protocol completes (all 3 mixes dispensed), use `camera_capture` **once** to capture the entire wellplate showing the whole wellplate with 3 mixed colours. Save the image as:
```
colour-RGB-<Sample name that user input>-<N>.jpg
```
Use the exact sample name provided by the user in the filename. `<N>` is the run number and must increment for every new run so images never overwrite earlier files. Do not omit `<N>`, and do not save the file as only `colour-RGB-<Sample name>.jpg`.

Run numbering for image filenames:
- `x_init` image -> `colour-RGB-<Sample name that user input>-1.jpg`
- First BO/LLM-suggested run -> `colour-RGB-<Sample name that user input>-2.jpg`
- Second BO/LLM-suggested run -> `colour-RGB-<Sample name that user input>-3.jpg`
- Continue increasing by 1 for every later run

> **Important**: Capture ONE image after the `x_init` protocol is dispensed, and then ONE image after each later optimization iteration — not one image per mix.

**Step 3a — Image processing (`x_init` and every optimization iteration)**
The image processing pipeline uses fixed, calibrated parameters — no VLM is needed. Call `run_pipeline()` on the captured image. The steps run in this exact order:
1. Apply fixed perspective correction using calibrated `src_corners` and `dst_corners` → flat deck image
2. Slice the warped plate image into a `row_num × col_num` ROI grid (one patch per well)
3. Compute median RGB for each requested well by `well_id`

All parameters are stored in `DEFAULT_CONFIG` in `image_processing.py`. Re-calibrate only if the camera is physically moved. See [image-processing.md](image-processing.md) for the full field reference.

---

### Phase 2 — Per-Iteration Loop

**Step 4 — Image processing**
Call `run_pipeline(image_path, well_ids, config=DEFAULT_CONFIG)` on the captured image. The pipeline uses fixed calibrated parameters for perspective correction and ROI slicing.

See [image-processing.md](image-processing.md).

**Step 5 — ROI extraction for all wells**
Slice the warped plate image into one ROI patch per well, in row-major order (left to right, top to bottom). This covers every well on the plate regardless of whether it has a mix or is empty.

**Step 6 — RGB extraction from active wells**
Compute the median RGB for each extracted ROI patch. Then select the RGB values for the wells that contain the mixes (by `well_id`, derived from the protocol's well assignments):
- Well index for A1 → `(R_mix_1, G_mix_1, B_mix_1)`
- Well index for A2 → `(R_mix_2, G_mix_2, B_mix_2)`
- Well index for A3 → `(R_mix_3, G_mix_3, B_mix_3)`

**Step 7 — RMSE calculation**
Compute RMSE for each well that received a mix:
```
RMSE = sqrt(((R_mix - R_target)² + (G_mix - G_target)² + (B_mix - B_target)²) / 3)
```
Use [../scripts/rmse.py](../scripts/rmse.py). For the 3 initial mixes this produces `RMSE_1`, `RMSE_2`, `RMSE_3`.

**Step 8 — Optimizer feedback**
Pass all `(volume_ratios, RMSE)` pairs (one per active well) to the chosen optimizer:
- **BO**: seed the surrogate model with all 3 initial `(ratio, RMSE)` observations
- **LLM**: provide the full list of `(ratios, RGB, RMSE)` for all 3 initial mixes and request the next suggestion

**Step 9 — New volume ratio suggestion**
The optimizer returns the next `(R_vol, G_vol, B_vol)` to try.

**Step 10 — Iteration report**
For each new set of optimization, create a new report file named `logs/colour-mixing-report-<sample name that user input>.md`. Do not count the 3 `x_init` mixes as iterations. First, append one `x_init` log block to that report file after the initial protocol finishes, then start iteration counting from the first parameter set suggested by BO or LLM and append one block after every optimization iteration.

The `x_init` log block must record:
- RMSE for all 3 initial mixes
- The 3 initial volume ratios and measured RGB values

Example `x_init` log block:

```markdown
## x_init

| Field | Value |
|---|---|
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |

### Wells processed in x_init

| Well | Volume ratio (R, G, B µL) | Mixed colour RGB | RMSE |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

```markdown
## Iteration <N>

| Field | Value |
|---|---|
| Iteration | <N> |
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |
| Next suggested ratio (R, G, B) | (<R_next> µL, <G_next> µL, <B_next> µL) |
| Stop condition reached | Yes / No |

### Wells processed this iteration

| Well | Volume ratio (R, G, B µL) | Mixed colour RGB | RMSE |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

The 3 initial `x_init` mixes are seed observations, not iterations, so they should not be written as `Iteration <N>` blocks. However, their RMSE values and well data must still be recorded in the `x_init` log block. Each optimization iteration block should have 1 row in "Wells processed" for the single BO/LLM-suggested mix.

**Step 11 — Generate and execute protocol**
Use **puda-protocol** to generate a new protocol with the suggested volumes and execute it on the Opentrons.

---

### Phase 3 — Stop Condition

Stop when **either** is met:

| Condition | Description |
|---|---|
| `RMSE ≤ threshold` | Target colour matched within acceptable error |
| `iteration ≥ max_iter` | Maximum optimization iterations reached (not counting the 3 `x_init` mixes) |

On stop: generate a final summary report and save it to `logs/colour-mixing-report-<sample name that user input>.md`.

## Rules

- Always ask for target colour, RMSE threshold, and max iterations **before** starting.
- Always collect **three separate deck slots** for R, G, and B dye source labware before any `load_labware` for those sources; never use one slot for all three.
- Always ask the user for explicit confirmation after all required inputs are collected and validated, before the first protocol is generated or executed.
- Never ask the user to paste API keys, tokens, passwords, or other secrets into chat.
- If `LLM` optimization requires credentials such as `OPENROUTER_API_KEY`, require them to be pre-configured in the local environment outside the chat before running.
- If the required LLM credential is missing, stop and tell the user to set it locally, but do not ask them to reveal the secret value and do not write the secret into prompts, config files, protocol files, or shell commands.
- Never assume volume ratios — they must come from the optimizer at each iteration.
- Image names must follow `colour-RGB-<Sample name that user input>-<N>.jpg` exactly, where `<N>` is the run number and increments on every run.
- Protocol must always end with no tip attached (Opentrons sequencing rule).
- Invoke **puda-memory** after every protocol creation and run.
- **If unsure about any input, parameter, or decision — ask the user. Do not assume.**
