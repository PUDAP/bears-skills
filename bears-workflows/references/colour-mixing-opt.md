---
name: colour-mixing-opt
description: Iteratively mix RGB colours on an Opentrons OT-2 and minimize RMSE between the mixed colour and a target colour using real-time camera feedback and BO or LLM optimization.
---

# Colour Mixing Optimization

Iteratively mix RGB colours on an Opentrons OT-2 and minimize RMSE to a target RGB using camera feedback plus BO or an LLM optimizer.

## Required Skills

- **puda-machines** for Opentrons liquid handling and `camera_capture`
- **puda-protocol** for protocol generation and execution
- **puda-memory** after every protocol creation and run

## Required Machine

- **Opentrons OT-2** with camera attached (`machine_id: "opentrons"`)

## Optimization Approach

Ask the user to choose the optimizer if not specified:

| Approach | When to use |
|---|---|
| **BO** | Efficient for continuous volume ratios; usually converges faster |
| **LLM** | Useful when colour-theory or qualitative reasoning matters |

See [optimization.md](optimization.md) for model and implementation details.

## Core Rules

- Only one active run at a time.
- Every iteration must use a new protocol and a new `run_id`.
- Never reuse, modify, or overwrite an earlier protocol.
- Never start a run while another run is active.
- Never send `play` twice to the same run.
- Poll every run until terminal state.
- Continue only if `run.status == "succeeded"`. Otherwise stop, log the failure, and recover before continuing.

## Phase 1 Setup

Collect and confirm all of the following before generating any protocol:

| Input | Description |
|---|---|
| Sample name | Used in protocol, image, and report filenames |
| Target colour | `(R, G, B)` with values `0-255` |
| Total well volume | Final volume per mixed well in �L |
| R / G / B source deck slots | Ask separately; never reuse one slot for all three |
| `x_init` mixes | Exactly 3 user-provided `(R, G, B)` volume sets |
| `x_init` destination wells | 3 user-selected wells, one per seed mix |
| Starting tip position | First tip for the first run |
| Optimization approach | BO or LLM |
| RMSE threshold | Stop when RMSE is at or below this value |
| Maximum iterations | Does not count the 3 `x_init` seed mixes |

Validation rules:

- Each `x_init` volume set must sum to `total_volume` within `�1 �L`.
- The 3 `x_init` destination wells must be explicit and distinct.
- Map aspirate sources to the user?s R, G, and B slots explicitly.
- Do not proceed until the user confirms the full setup summary.

The confirmation summary must include the sample name, target colour, total volume, R/G/B slots, all 3 `x_init` volume sets, all 3 `x_init` destination wells, starting tip position, optimizer choice, RMSE threshold, and maximum iterations.

## Phase 2 ? Initial Run

Generate one protocol for the 3 `x_init` mixes and dispense them into the 3 user-selected destination wells.

Protocol defaults:

- Use direct source-to-destination transfers only.
- Do not aspirate from a destination well and dispense back into the same well.
- Do not use Opentrons `mix()` or `mix_after` unless the user explicitly asks for active in-well mixing.
- Each `x_init` mix should fill its assigned well once up to the requested total volume.
- Tip usage must follow row-major order:

```text
A1, A2, A3, ... A12, B1, B2, ... H12
```

- Start the first run from the user-selected tip.
- After each run, record the last tip used; the next run must start from the next tip in the same sequence.
- Protocol filenames must include the exact sample name.

Run sequence:

1. Upload protocol.
2. Create run and store `run_id`.
3. Verify no other run is active and the robot is not in an error state.
4. Start the run.
5. Poll until terminal state.

After the `x_init` run succeeds, capture one whole-plate image:

```text
colour-RGB-<Sample name that user input>-1.jpg
```

Use one image per run, not one image per mix. Increment the final number for every later run.

## Phase 3 ? Measure and Optimize

For every successful run:

1. Call `run_pipeline(image_path, well_ids, config=DEFAULT_CONFIG)`.
2. Apply the fixed perspective correction and ROI slicing defined in `image_processing.py`.
3. Extract median RGB values for the wells used in that run.
4. Compute RMSE for each active well using `../scripts/rmse.py`:

```text
RMSE = sqrt(((R_mix - R_target)^2 + (G_mix - G_target)^2 + (B_mix - B_target)^2) / 3)
```

5. Pass observations to the optimizer:
   - **BO**: all `(ratio, RMSE)` pairs
   - **LLM**: all `(ratio, RGB, RMSE)` pairs
6. Get the next suggested `(R_vol, G_vol, B_vol)`.
7. Generate and execute a brand-new protocol for that next run.

See [image-processing.md](image-processing.md) for the image pipeline details.

## Reporting

Create `logs/colour-mixing-report-<sample name that user input>.md`.

- Treat the 3 `x_init` mixes as seed observations, not iterations.
- Append three seed sections: `x_init 1`, `x_init 2`, `x_init 3`.
- Start optimizer-generated runs at `Iteration 1`.
- Each `x_init` section records one seed mix only.
- Each later iteration section records the single optimizer-suggested mix for that run.

Each report entry should include:

- Image filename
- Target RGB
- Well used
- Volume ratio `(R, G, B)`
- Measured RGB
- RMSE
- For optimizer iterations, the next suggested ratio and whether the stop condition was reached

## Stop Condition

Stop when either condition is met:

| Condition | Description |
|---|---|
| `RMSE <= threshold` | Target colour matched closely enough |
| `iteration >= max_iter` | Maximum optimization iterations reached |

On stop, write the final summary to `logs/colour-mixing-report-<sample name that user input>.md`.

## Rules

- Never assume missing inputs; ask the user.
- Never ask the user to paste secrets into chat.
- If an LLM optimizer requires credentials such as `OPENROUTER_API_KEY`, require them to be set locally outside chat.
- Image names must follow `colour-RGB-<Sample name that user input>-<N>.jpg`.
- Every new run must create a new protocol.
- `x_init` wells must come from the user, not from a hardcoded mapping.
- Tip continuation must resume from the next tip after the last tip used.
- Default colour-mixing protocols must not generate destination-well mixing loops or random tip pickup.
- Protocols must end with no tip attached.
- Invoke **puda-memory** after every protocol creation and run.
