---
name: colour-mixing-opt
description: Run recursive self-improvement colour mixing with separate evaluator and executor agents, using measured RGB feedback to suggest and safely execute the next RGBy parameters.
---

# Recursive Self-Improvement Colour Mixing Optimization

Use a strict evaluator-agent to executor-agent loop. After each successful run, the executor returns measured RGB and experiment evidence to the evaluator. The evaluator assesses the result and proposes the next red, green, blue, and water volumes. A separate executor validates and runs that proposal.

## Required Skills

Invoke these skills before generating any commands:
- **puda-machines** → opentrons machine (liquid handling + `camera_capture`)
- **puda-protocol** → protocol generation and execution
- **puda-memory** → update `experiment.md` after every protocol creation and run
- **puda-report** → resolve the report **save path / output folder** only (the report filename and markdown layout are defined in this document)

## Required Machine

- **Opentrons OT-2** with camera attached (`machine_id: "opentrons"`)

## Core Principle 
The system must operate in a strict single-run, sequential two-agent loop.
At any time:
- Only **One active run** is allowed 
- Each iteration sues a **NEW run_id**
-No downstream step executres unless the run is **confirmed successful**
- Every mix must contain four explicitly specified components: **red, green, blue, and water**. Never generate a colour-mixing protocol from only R, G, and B volumes.
- The **evaluator agent** may evaluate measured RGB/history and suggest parameters, but must not generate, upload, or execute a protocol.
- The **executor agent** may validate and execute the evaluator's exact numeric suggestion, but must not silently alter or replace it.
- Never allow one agent to perform both roles within an iteration.
- Every target, initialization, and iteration capture requires a new capture-scoped calibration measured from that exact image. Never reuse calibration coordinates between captures and never use `DEFAULT_CONFIG` for RGB measurement.


## Optimization Approach

The RSI evaluator agent is the decision maker. It examines raw measured RGB, target RGB, executed RGBY parameters, and experiment history; chooses and documents its own evaluation method; and hands one next experiment to a separate executor. See [optimization.md](optimization.md) for the contract.

---

## Workflow

### Phase 0 — Run Lifecycle Safety

This applies to every iteration.

Mandatory Rules
-Never send play twice on same run
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
| Target colour source | Choose either `manual_rgb` or `measured_target_mix` |
| Target colour — if `manual_rgb` | `(R, G, B)` where each value is 0–255 |
| Target mix volumes — if `measured_target_mix` | One `(R_vol, G_vol, B_vol, water_vol)` set in µL to dispense, capture, process, and use as the target RGB |
| Target mix volume well — if `measured_target_mix` | Mapping of the target mix volume set to the destination well, for example `(100, 100, 100, 0) µL -> C1` |
| Target mix destination well — if `measured_target_mix` | Well used for the target-mix calibration run; this target well is not an optimization seed well |
| Total well volume | Total volume in µL per well (e.g. 300 µL) |
| **R dye source — deck slot** | OT-2 deck slot (`"1"`–`"11"`) for the labware holding **red** dye only |
| **G dye source — deck slot** | Deck slot for the labware holding **green** dye only |
| **B dye source — deck slot** | Deck slot for the labware holding **blue** dye only |
| **Water source — deck slot** | Deck slot for the labware holding **water only** |
| `x_init` — 3 initial mixes | User-provided volume sets (see below) |
| `x_init` destination wells | Three user-selected destination wells, one for each `x_init` mix |
| Optimization approach | RSI evaluator agent |
| Maximum iterations | Stop after this many iterations; default and maximum allowed value is 12 |

**Critical — RGB dye labware and water source use separate deck positions**

The R, G, and B dyes are loaded as **three independent `load_labware` calls** with **three separate `location` values**, and the water source must also have its own dedicated deck slot. You must **ask the user for each slot individually** (R, then G, then B, then water — or present one form with four distinct fields). **Do not** ask a single question such as “which slot is the dye plate?” and reuse that answer for R, G, and B. **Do not** assume all three dye plates share the same slot, and do not reuse a dye slot for water.

When generating protocols, map aspirate sources to the user’s **R slot / G slot / B slot / water slot** explicitly. Each mix must aspirate from the separate **red**, **green**, **blue**, and **water** sources using the user-confirmed deck slots — never copy one slot onto all three dye labware loads or reuse a dye slot for water.

**Target colour source**

Ask the user how the target RGB should be obtained before starting:

| Option | Workflow |
|---|---|
| `manual_rgb` | Use the existing method: the user directly provides the target `(R, G, B)` values, each 0-255. |
| `measured_target_mix` | The user provides one red/green/blue/water volume combination. Generate and run a target-mix protocol, capture an image, process the target well, and use the measured arithmetic-mean inner-well RGB as the target for optimization. |

For `manual_rgb`:
- Validate that the provided target has exactly three numeric values.
- Validate that every value is between 0 and 255.
- Use this RGB tuple directly as `(R_target, G_target, B_target)`.
For `measured_target_mix`:
- Ask for one target mix volume set `(R_vol, G_vol, B_vol, water_vol)` in µL.
- Validate that the target mix volumes sum to `total_volume` (±1 µL tolerance): `R+G+B+water=total_volume`.
- Ask for the destination well used for this target-mix calibration run.
- Record the target mix volume well mapping explicitly, for example `(R_vol, G_vol, B_vol, water_vol) -> target_well`.
- Generate a standalone protocol that dispenses only this target mix.
- Execute the protocol, then capture one whole-wellplate image.
- Recalibrate `src_corners` and `well_center_corners` from that target image, create a unique capture-scoped configuration with `create_capture_calibration(...)`, and call `run_pipeline(..., calibration_capture_id=target_capture_id)`.
- Use the measured arithmetic-mean inner-well RGB from `target_well` as `(R_target, G_target, B_target)` for all later evaluator comparisons.
- Do not include the target-mix calibration well in `x_init` observations or optimizer history.
- If protocol execution, image capture, or image processing fails, stop before generating `x_init` and require recovery.

After deriving the measured target RGB, record it as the target colour and continue to `x_init` without asking for another user confirmation.

**`x_init` — Initial volume inputs**

Ask the user to provide exactly 3 initial volume combinations for R, G, B, and water in µL. Each set must sum to the total well volume.
Validate each set before generating the protocol — reject and re-ask if any set does not sum to `total_volume` (±1 µL tolerance).
Do not accept or auto-fill three-component `(R, G, B)` seed mixes. Water must be supplied explicitly in every `x_init` tuple.

Ask the user to choose exactly 3 destination wells for `x_init`, one well for each initial volume combination.

Validation rules:
- Each `x_init` well must be a valid well ID for the destination labware.
- The 3 `x_init` wells must be unique.
- The selected wells must be mapped explicitly to the 3 initial volume combinations, for example: `x_init 1 -> B1`, `x_init 2 -> B2`, `x_init 3 -> B3`.
- If `measured_target_mix` used a well in the same destination plate, the `x_init` wells must not include the target well unless the user explicitly confirms the plate has been cleared or replaced.
- Do not assume `A1`, `A2`, and `A3`; use only the wells confirmed by the user.

**Step 1a — User confirmation before execution**
After all inputs have been collected and validated, present a setup summary back to the user that also states the labware positions, and ask for explicit confirmation before generating or executing any protocol.

The confirmation summary must include:
- Sample name
- Target colour source
- Total well volume
- Labware positions
- R / G / B / water source deck slots
- If `manual_rgb`: target colour RGB
- If `measured_target_mix`: target mix volumes, target mix destination well, target mix volume well mapping, and planned target image filename
- All 3 `x_init` volume combinations
- All 3 `x_init` destination wells and their mapping to the initial volume combinations
- Optimization approach
- Maximum iterations


Do not generate the `x_init` protocol until the user confirms that the full setup is correct.

If `measured_target_mix` is selected, the target-mix calibration protocol may be generated and executed only after the user confirms the target-mix setup. After the target image is processed successfully, continue directly to `x_init` using the measured target RGB.

**Step 2 — Initial mixes (`x_init`)**
Generate a single protocol that dispenses all 3 initial volume combinations into the 3 user-selected `x_init` destination wells and execute it on the Opentrons. Each mix must combine **red, green, blue, and water** from their respective source labware. Record which confirmed well received which `(R_vol, G_vol, B_vol, water_vol)` set.

If `measured_target_mix` used a well in the same destination plate, reserve that target well and do not reuse it for `x_init` or later optimization wells unless the user explicitly confirms the plate has been cleared or replaced.

Tip usage must advance in row-major order on the tip rack:

```text
A1, A2, A3, ... A12, B1, B2, ... H12
```
Use a new tip for every non-zero component transfer. A single tip must never be reused across red, green, blue, or water sources. For each non-zero component, the generated protocol must follow:

```python
pipette.pick_up_tip(next_tip)
pipette.aspirate(component_volume, component_source)
pipette.dispense(component_volume, dest_well)
pipette.blow_out(dest_well.top())
pipette.drop_tip()
```

Then advance to the next row-major tip for the next non-zero component. Skip zero-volume components and do not pick up a tip for them.

Use tips strictly in row-major order across the target-mix calibration run, `x_init`, and all later iterations. Tip counts are based on non-zero component transfers, not wells. For example, one mix with non-zero red, blue, and water uses 3 tips. Three `x_init` mixes with all four components non-zero use 12 tips. If `manual_rgb` is used and the first `x_init` mix has all four components non-zero, it must use `A1`, `A2`, `A3`, `A4`; the next mix continues with `A5`. If `measured_target_mix` uses four non-zero components first, that target run must use `A1` through `A4`, and `x_init` must continue from `A5`.

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
- If `manual_rgb` is used: `x_init` image -> `colour-RGB-<Sample name that user input>-1.jpg`
- If `measured_target_mix` is used: target-mix image -> `colour-RGB-<Sample name that user input>-1.jpg`, then `x_init` image -> `colour-RGB-<Sample name that user input>-2.jpg`
- First evaluator-suggested run -> next available `<N>` after `x_init`
- Second evaluator-suggested run -> next available `<N>` after the first evaluator-suggested run
- Continue increasing by 1 for every later run

> **Important**: Capture ONE image after the `x_init` protocol is dispensed, and then ONE image after each later optimization iteration — not one image per mix.

If `measured_target_mix` is used, also capture ONE image after the target-mix calibration protocol. This target image is used only to derive `(R_target, G_target, B_target)` and is not counted as `x_init` or as an optimization iteration.

**Step 3a — Image processing (`x_init` and every optimization iteration)**
For the target, `x_init`, and every optimization iteration, use the newly captured full-resolution measurement image itself as the calibration image. Recalculate geometry from that image and create a unique capture-scoped configuration with `create_capture_calibration(...)`. Do this even when the camera and plate appear unchanged. Do not measure RGB until the current capture's calibration artifacts have been inspected and accepted. The steps run in this exact order:
1. Save a perspective-corrected plate overview using calibrated `src_corners` and `dst_corners`
2. Use calibrated raw-image centres `[A1, A12, H12, H1]` to bilinearly interpolate all 96 well centres
3. Extract one centred `8 × 8` raw-pixel patch fully inside each well opening
4. Compute arithmetic-mean RGB from the exact pixels in each patch
5. Save the raw-image ROI alignment, all-well patch/RGB montage, and RGB/coordinate CSV

`DEFAULT_CONFIG` is documentation-only and is rejected for RSI measurements. Bind each new configuration to the exact current image path and SHA-256, use it once, then discard it. See [image-processing.md](image-processing.md) for the mandatory procedure.

---

### Phase 2 — Per-Iteration Loop

**Step 4 — Image processing**
Call `run_pipeline(image_path, well_ids, config=capture_config, calibration_capture_id=current_capture_id)` on each fresh captured image. The function must reject default geometry, run-scoped calibration, a different path, changed image bytes, or a different capture ID. The raw-image corner-well centres and inner-well patches are the RGB source; the warped image is retained as an inspection artifact.

For the `x_init` image, `well_ids` must be the 3 user-selected `x_init` destination wells in the same order as the confirmed `x_init` mapping.

See [image-processing.md](image-processing.md).

**Step 5 — ROI extraction for all wells**
Interpolate all 96 centres from `[A1, A12, H12, H1]`, with A1 at top-left. Extract a centred square patch from the raw image for each well in row-major order. Every patch must remain inside the inner-well opening and exclude the well rim and surrounding plate.

**Step 6 — RGB extraction from active wells**
Compute arithmetic-mean RGB from every raw pixel in each inner-well patch. Save all-well ROI/RGB artifacts, then select the RGB values for wells containing mixes (by `well_id`, derived from the protocol's well assignments):
- User-selected `x_init 1` well → `(R_mix_1, G_mix_1, B_mix_1)`
- User-selected `x_init 2` well → `(R_mix_2, G_mix_2, B_mix_2)`
- User-selected `x_init 3` well → `(R_mix_3, G_mix_3, B_mix_3)`

**Step 7 — Raw observation packaging**
Preserve the executed RGBY volumes, measured RGB, target RGB, run ID, iteration number, and complete history. Do not calculate or prescribe a colour-error score before evaluator handoff.

**Step 8 — Optimizer feedback**
Build an evaluation request with [rsi_handoff.py](../../scripts/RSI%20optimization/rsi_handoff.py). Include the latest run ID, iteration, executed `(R, G, B, water)` volumes, measured RGB, target RGB, total volume, and complete prior history. Pass that immutable request to a dedicated evaluator agent.

The evaluator decides how to assess each RGB result from the supplied observation and history. It must name, define, calculate, and justify its selected method, then use that assessment to recommend the next RGBY parameters. It may switch methods between iterations when its explanation makes the change auditable. No fixed metric or optimizer selects the next experiment outside the evaluator.

**Step 9 — New volume ratio suggestion**
The evaluator returns exactly one `rsi_colour_mixing_handoff` JSON object. It must contain the source observation SHA-256, next sequential iteration number, evaluator-defined `evaluation_method`, concise evaluation, and a decision.

- For `execute_next_iteration`, include exactly four suggestion fields (`red_ul`, `green_ul`, `blue_ul`, and `water_ul`) and `workflow_change: {"action": "none"}`.
- For `propose_workflow_change`, include a concrete proposal, rationale, and `requires_user_approval: true`. Do not include executable parameters. This decision pauses the loop.

`evaluation_method` must declare `name`, `source: "evaluator_defined"`, `goal` (`minimize` or `maximize`), finite numeric `value`, plain-language `definition`, reproducible `calculation`, and `uses_only_observation_data: true`. Record this declaration in the report. Do not accept an opaque score without its definition and calculation.

Pass the handoff to a separate executor agent. Before any protocol generation, call `validate_evaluator_handoff(...)` from [rsi_handoff.py](../../scripts/RSI%20optimization/rsi_handoff.py). Reject stale observation hashes, skipped/repeated iterations, missing or extra fields, non-finite or negative values, and volume totals outside `total_volume` (±1 µL). The executor must not repair an invalid suggestion; return the validation error to the evaluator for a new handoff.

If validation returns `executable: false`, stop and present the workflow-change proposal to the user. Do not modify code, image processing, protocols, safety gates, labware, or execution behavior until the user explicitly approves it. After approval, update and validate the workflow as a separate change, record the approval, then request a fresh evaluator handoff bound to the latest observation.

After validation, the executor must:
1. Present the exact suggested volumes and evaluator reasoning for approval when physical execution requires approval.
2. Generate and inspect a protocol from only the validated numeric suggestion.
3. Execute one new run, poll it to a terminal state, and continue only when it succeeded.
4. Capture and process the new image, then return the new measured RGB and run evidence as the next evaluation request.

This executor-to-evaluator return closes one recursive self-improvement cycle. Repeat with a fresh observation hash and run ID; never reuse an earlier handoff.

**Step 10 — Iteration report**
For each new set of optimization, create a new report file named `colour-mixing-report-<sample name that user input>.md`. Defer to the **puda-report** skill only for the save path / output folder — the filename above and the markdown layout described below in this document are authoritative (puda-report decides **where** the file is written, not **how** it is written). Do not count the 3 `x_init` mixes as iterations. After the initial protocol finishes, append three separate seed log blocks titled `x_init 1`, `x_init 2`, and `x_init 3` (one block per initial mix). Then start optimization iteration counting from the first parameter set suggested by the evaluator and append one block after every optimization iteration.

Each `x_init` log block must record:
- Which seed run it is: `x_init 1`, `x_init 2`, or `x_init 3`
- The user-selected destination well for that seed run
- The evaluator's selected method, value, and assessment for that initial mix
- The volume ratio and measured RGB value for that initial mix only

If `measured_target_mix` was used, the report must also record a target calibration block before the `x_init` blocks:
- Target colour source: `measured_target_mix`
- Target mix volume ratio
- Target mix destination well
- Target image filename
- Measured target RGB used for optimization

Example target calibration log block:

```markdown
## Target Colour Calibration

| Field | Value |
|---|---|
| Target colour source | measured_target_mix |
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target well | <target_well> |
| Target mix volume ratio (R, G, B, water µL) | (<R_vol>, <G_vol>, <B_vol>, <water_vol>) |
| Measured target colour RGB | (<R_target>, <G_target>, <B_target>) |
```

Example `x_init` log block:

```markdown
## x_init 1

| Field | Value |
|---|---|
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |

### Wells processed in x_init 1

| Well | Volume ratio (R, G, B, water µL) | Mixed colour RGB | Evaluator assessment |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>, <water_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

```markdown
## Iteration <N>

| Field | Value |
|---|---|
| Iteration | <N> |
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |
| Next suggested ratio (R, G, B, water) | (<R_next> µL, <G_next> µL, <B_next> µL, <water_next> µL) |
| Evaluation method | <name, goal, definition, and reproducible calculation> |
| Evaluation value | <finite value calculated by the evaluator> |
| Evaluator assessment | <interpretation of the RGB result and history> |
| Evaluator next-parameter rationale | <why the suggested RGBY volumes should be tested next> |
| Stop condition reached | Yes / No |

### Wells processed this iteration

| Well | Volume ratio (R, G, B, water µL) | Mixed colour RGB | Evaluator assessment |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>, <water_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

The 3 initial `x_init` mixes are seed observations, not iterations, so they should not be written as `Iteration <N>` blocks. They must instead be recorded as three separate blocks titled `x_init 1`, `x_init 2`, and `x_init 3`. After those seed entries, the first evaluator-suggested run must be recorded as `Iteration 1`, then `Iteration 2`, `Iteration 3`, and so on. Each iteration block has one row for the single evaluator-suggested mix and records the evaluator's method, value, assessment, and rationale.

**Step 11 — Generate and execute protocol**
Use **puda-protocol** to generate a new protocol with the suggested volumes and execute it on the Opentrons.

**Critical - Liquid volume execution must match the optimizer tuple exactly**

Generate colour-mixing Opentrons Python with the helper [../../scripts/optimization_workflow/build_colour_mixing_protocol.py](../../scripts/optimization_workflow/build_colour_mixing_protocol.py). Do not freehand `upload_and_run` Python for colour-mixing liquid transfers unless the helper is unavailable and the generated code is manually checked against the rules below.

For every target mix, `x_init` mix, and evaluator-suggested iteration:
- Treat `(R_vol, G_vol, B_vol, water_vol)` as absolute dispense volumes in uL, not as volumes to repeat.
- For each non-zero component, generate exactly one explicit fresh-tip aspirate-dispense block from that component source into the destination well unless a single component volume exceeds the selected pipette's maximum capacity. Do not use `transfer()` or `distribute()` for colour-mixing liquid additions, because those helpers can introduce extra aspiration-like motions such as disposal volume, refills, or blow-out return behavior. With a `p300`, a 300 uL component is one aspirate and one dispense operation, not two.
- The generated Python for each non-zero component must follow this exact liquid-handling pattern with a fresh tip: one `pipette.pick_up_tip(next_tip)`, one `pipette.aspirate(component_volume, component_source)`, one `pipette.dispense(component_volume, dest_well)`, one `pipette.blow_out(dest_well.top())`, and one `pipette.drop_tip()` before moving to the next component. Do not reuse a tip between components. Do not insert a second aspirate, pre-wet aspirate, air-gap aspirate, disposal-volume aspirate, touch-volume aspirate, or any other liquid-moving command before the matching dispense.
- If a component volume exceeds the pipette's maximum capacity, split only that component into chunks whose sum equals the requested component volume. The split chunks must not add any extra volume.
- Do not use protocol-level `mix`, `pipette.mix(...)`, `mix_before`, `mix_after`, repeated transfer loops, or duplicate aspirate/dispense commands as a substitute for colour mixing. A generated colour-mixing protocol should show only fresh-tip component transfers needed to deliver `(R_vol, G_vol, B_vol, water_vol)`, with `blow_out` and `drop_tip` after every non-zero component and safe movement/home as needed.
- Keep `pipette.blow_out(dest_well.top())` after each component dispense to complete delivery from that component's tip. Because the tip is dropped immediately after `blow_out`, the next component must start with a fresh `pick_up_tip(next_tip)` before aspirating from its source.
- If the user explicitly requests post-dispense mixing, confirm it separately before execution and state that `pipette.mix(repetitions, volume, dest_well)` will appear as extra aspirate/dispense cycles in the destination well. Those cycles must be excluded from source-volume accounting and must not aspirate from any source well.
- After protocol generation, compute the planned liquid added to each destination well from the actual pipetting commands. Reject and regenerate the protocol if any destination well receives more than `total_volume` (+/-1 uL tolerance), even if the optimizer suggestion itself summed to `total_volume`.
- Before uploading a colour-mixing protocol, inspect the generated Python text. For an iteration with four non-zero components, the protocol must contain exactly four explicit `pipette.pick_up_tip(...)` calls, four explicit `pipette.aspirate(...)` calls, four explicit `pipette.dispense(...)` calls, four explicit `pipette.blow_out(...)` calls, and four explicit `pipette.drop_tip()` calls, with no tip reused between components and no `pipette.mix(...)`, `air_gap`, `transfer`, `mix_before`, or `mix_after`. For zero-volume components, omit that component's full pick-up/aspirate/dispense/blow-out/drop-tip block and reduce the expected count accordingly.

---

### Phase 3 — Stop Condition

Stop only when the maximum optimization iteration limit is reached.

| Condition | Description |
|---|---|
| `iteration >= max_iterations` | Maximum optimization iterations reached (not counting the 3 `x_init` mixes) |

After every optimization iteration, record the evaluator's method, value, assessment, and next-parameter rationale. Do not stop early based on an evaluator score. Continue until `iteration >= max_iterations`, then stop and mark `Stop condition reached` as `Yes` in the final iteration report block.

On stop: generate a final summary report using the markdown structure defined in this document, and write it to `colour-mixing-report-<sample name that user input>.md` at the save path resolved by the **puda-report** skill.

## Rules

- Always ask for target colour source before starting.
- Ask for the maximum optimization iterations before starting. The default and maximum allowed value is 12.
- Stop optimization only when the configured maximum optimization iterations have been reached. The 3 `x_init` mixes are seed observations and do not count toward the iteration limit.
- If target colour source is `manual_rgb`, validate and use the user-provided target RGB.
- If target colour source is `measured_target_mix`, run the target-mix calibration, process the target well image, and use the measured RGB as the target before generating `x_init`.
- Recalibrate every target, `x_init`, and iteration image independently. Create a unique capture-scoped `ImageConfig` from that exact image and never carry calibration into another capture.
- Always ask the user to choose exactly 3 unique `x_init` destination wells; never assume `A1`, `A2`, and `A3`.
- Always collect **four separate deck slots** for R, G, B, and water source labware before any `load_labware` for those sources; never use one slot for all three dyes or reuse a dye slot for water.
- Every target mix, `x_init` mix, evaluator suggestion, generated protocol, and report row must include explicit **red, green, blue, and water** volumes.
- Validate all `(R_vol, G_vol, B_vol, water_vol)` tuples before protocol generation: each value must be numeric and non-negative, and `R+G+B+water` must equal `total_volume` within ±1 µL.
- Always ask the user for explicit confirmation after all required inputs are collected and validated, before the first protocol is generated or executed.
- Never ask the user to paste API keys, tokens, passwords, or other secrets into chat.
- If `LLM` optimization requires credentials such as `OPENROUTER_API_KEY`, require them to be pre-configured in the local environment outside the chat before running.
- If the required LLM credential is missing, stop and tell the user to set it locally, but do not ask them to reveal the secret value and do not write the secret into prompts, config files, protocol files, or shell commands.
- Never assume volume ratios — they must come from the optimizer at each iteration.
- In RSI mode, treat evaluator prose as report-only content. Generate protocols only from the four numeric fields in a handoff that passed `validate_evaluator_handoff(...)`.
- Preserve the complete observation and handoff history. Bind every suggestion to the immediately preceding observation SHA-256 and reject stale or replayed handoffs.
- Keep evaluator and executor responsibilities separate. The evaluator cannot operate the OT-2; the executor cannot choose or modify the next parameters.
- Require the evaluator to define a reproducible assessment method from the immutable observation/history for every decision. If that method needs new images, sensors, preprocessing, calibration, or unavailable data, treat it as a workflow-change proposal requiring explicit user approval. Apply the same rule to protocol, stop-condition, labware, safety-gate, and execution-sequence changes.
- Image names must follow `colour-RGB-<Sample name that user input>-<N>.jpg` exactly, where `<N>` is the run number and increments on every run.
- Tip pickup order must be strictly `A1, A2, ... A12, B1, B2, ... H12`
- Protocol must always end with no tip attached (Opentrons sequencing rule).
- Invoke **puda-memory** after every protocol creation and run.
- Use **puda-report** only to resolve the report **save path / output folder**. The report filename (`colour-mixing-report-<sample name that user input>.md`) and the markdown layout (`x_init N` blocks, `Iteration N` blocks, final summary) are defined in this document and must not be changed by puda-report.
- **If unsure about any input, parameter, or decision — ask the user. Do not assume.**
