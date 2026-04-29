---
name: viscosity-optimization
description: Optimize aspiration volume for viscous fluids on an Opentrons OT-2 so the dispensed volume is as close as possible to the target volume, using gravimetric feedback from a PUDA balance machine (Linux serial), driven by Bayesian Optimization (LCB or EO) or an LLM via OpenRouter.
---

# Viscosity Optimization

Iteratively tune the Opentrons OT-2 aspiration volume to minimize dispense-volume error (µL) for viscous liquids, using real-time gravimetric feedback from the PUDA balance machine and BO or LLM optimization.

## Required Skills

Invoke these skills before generating any commands:
- **puda-machines** → opentrons machine (liquid handling commands, labware) and balance machine (gravimetric mass readings)
- **puda-protocol** → protocol generation and execution
- **puda-memory** → update `experiment.md` after every protocol creation and run

## Required Hardware

- **Opentrons OT-2** — reachable on local network (confirm IP before starting)

## Core Principle 
The system must operate in a strict single-run, sequential execution loop.
At any time:
- Only **One active run** is allowed 
- Each iteration sues a **NEW run_id**
-No downstream step executres unless the run is **confirmed successful**

- **PUDA balance machine** — Arduino-based mass balance connected via Linux USB serial (`/dev/ttyUSB2` or `/dev/ttyACM2`)


## Required Machine References

Load these references before generating commands:
- `../bears-machines/references/opentrons-machine.md`
- `../bears-machines/references/balance-machine.md`

## Optimization Approaches

Ask the user which approach to use if not specified:

| Approach | Class | When to use |
|---|---|---|
| **Bayesian LCB (SO)** | `SOVH_LCB` | Good default; one scalar objective (e.g. abs error) |
| **Bayesian EO (SO)** | `SOVH_EO` | Noisy observations or tight iteration budget |
| **LLM (single objective)** | `SOVH_LLM` (alias `ViscosityLLMOptimizer`) | Optimize aspiration volume toward the target dispensed volume |
---

## Workflow

### Phase 1 — Initialization

**Step 1 — Inputs (ask user before proceeding)**

Collect all of the following before starting. Do not proceed until every value is confirmed.

**User Input**

| Input | Description |
|---|---|
| Sample name | String identifier (e.g. `"glycerol_50pct"`) |
| Initial volume | `initial_aspiration` in µL used in each protocol run |
| Target volume | µL expected to actually transfer |
| Optimization approach | `bayes_lcb`, `bayes_ei`, or `llm` |
| If LLM: OpenRouter model ID | e.g. `"openai/gpt-4o"` |
| Measurement phase | `"aspirate"` or `"dispense"` — which phase the balance records |
| Outlier threshold | Mass readings (mg) below this value are discarded |
| Max iterations | Upper bound on optimization iterations |
| Error threshold | Stop when absolute error ≤ this value in µL |
| Source labware | labware of source for aspiration |
| Source slot and well | where does the labware place |
| Destination labware | labware of source for aspiration |
| Destination slot and well | where does the labware place |
| Pipette type | which pipette used |
| Pipette location mount | `left` or `right`|
| Balance seriel port | `/dev/ttyUSB0` |

**Step 1a — User confirmation before execution**
After all inputs have been collected and validated, present a setup summary back to the user that also states the labware positions, and ask for explicit confirmation before generating or executing any protocol.

**Step 2 — Initial transfer ( `initial_aspiration` )**
Generate a single protocol that dispenses the initial volume to destination wells and execute it on the Opentrons. 

Tip usage must advance in row-major order on the tip rack:

```text
A1, A2, A3, ... A12, B1, B2, ... H12
```
Use tips strictly in that exact order across the `initial_aspiration`, and all later iterations. For example, `initial_aspiration` at `A1`, then iteration should start from  `A2`, and the next iteration must continue from `A3`.

**Execution Sequence (MUST FOLLOW EXACTLY)**
1. Upload protocol
2. Create run -> store `run_id`
3. Verify:
   - No active run
   - Robot not in error state
4. Start run (`play`)
5. Poll run status until terminal

The balance machine must be started before readings are collected, tared, checked for `fresh == True` before any mass value is used. 

**Step 3 — Collect concurrent data**

During the run, two concurrent threads record:
- Balance readings at **4 Hz** — reads fresh `get_mass()["mass_g"]`, converts to `mass_mg = mass_g * 1000`, and records `mass_mg` with `timestamp`
- OT-2 run status at **4 Hz** — `ot2_command`, `ot2_status`

Only readings where `get_mass()["fresh"] == True` (age < 5 s) are considered valid.

Raw data is saved as:
```
data/viscosity_raw_data/<sample>_init<NNN>_<YYYYMMDD_HHMMSS>.csv
```
**Step 4 — Process data**

Use [`../scripts/balance_data_process.py`](../scripts/balance_data_process.py) to merge protocol commands with balance readings and process the raw CSV:
1. Strip apostrophes from serial output
2. Remove outlier rows where `mass_mg` is below `outlier_threshold`
3. Forward-fill OT-2 command labels onto balance rows
4. Slice to the `measurement_phase` window only
5. Normalise `Time` and `mass_mg` to start at 0

Processed data is saved to:
```
data/viscosity_processed_data/<same filename>.csv
```

The single objective is to minimize `absolute_error` by adjusting only `aspiration_volume`.


### Phase 2 — Per-Iteration Loop

**Step 3 — Generate and run protocol**

Build the protocol with current optimizer-suggested parameter values and execute on the OT-2. The balance is tared (`driver.tare(wait=2.0)`) at the start of every iteration for a fresh zero baseline.

**Critical**
If the user provides custom source or destination labware, get the custom labware JSON definition from opentron driver and  include that JSON in the generated Opentrons protocol. Do not generate the protocol with only the custom labware name; the protocol must load the custom labware from the provided JSON definition.

Tip usage must start at `A1` and advance one tip per protocol run in row-major order:
```text
A1, A2, A3, A4, ... A12, B1, B2, ... H12
```
For example, iteration 1 uses `A1`, iteration 2 uses `A2`, iteration 3 uses `A3`, and iteration 4 uses `A4`. Do not reuse a tip or skip ahead unless the user explicitly confirms a new tip rack state.

**Step 4 — Collect concurrent data**

During the run, two concurrent threads record:
- Balance readings at **4 Hz** — reads fresh `get_mass()["mass_g"]`, converts to `mass_mg = mass_g * 1000`, and records `mass_mg` with `timestamp`
- OT-2 run status at **4 Hz** — `ot2_command`, `ot2_status`

Only readings where `get_mass()["fresh"] == True` (age < 5 s) are considered valid.

Raw data is saved as:
```
data/viscosity_raw_data/<sample>_iter<NNN>_<YYYYMMDD_HHMMSS>.csv
```

**Step 5 — Process data**

Use [`../scripts/balance_data_process.py`](../scripts/balance_data_process.py) to merge protocol commands with balance readings and process the raw CSV:
1. Strip apostrophes from serial output
2. Remove outlier rows where `mass_mg` is below `outlier_threshold`
3. Forward-fill OT-2 command labels onto balance rows
4. Slice to the `measurement_phase` window only
5. Normalise `Time` and `mass_mg` to start at 0

Processed data is saved to:
```
data/viscosity_processed_data/<same filename>.csv
```

**Step 6 — Compute transfer error**

```
measured_vol_µL = final processed balance-derived volume in µL
signed_error    = measured_vol_µL − target_volume_µL
absolute_error  = |signed_error|
```
The single objective is to minimize `absolute_error` by adjusting only `aspiration_volume`.

**Step 7 — Update optimizer**

For Bayesian SOVH in [`scripts/optimizers.py`](../scripts/optimizers.py), call ``observe({"aspiration_volume": value}, signed_error_ul, absolute_error_ul=...)`` (``absolute_error_ul`` defaults to ``|signed_error_ul|``). The surrogate uses signed error (EO: fit on ``-(signed_error_ul²)`` toward zero error; LCB: fit on absolute error with ``UpperConfidenceBound(..., maximize=False)``).

**Step 8 — Save iteration report**

Append one row/block to the report file after every iteration. This is the live optimization log. 

For Bayesian: `data/viscosity_report/report_<sample>.csv`
```
iteration, timestamp, approach, aspiration_volume_ul, measured_volume_ul, target_volume_ul, signed_error_ul, abs_error_ul
```

For LLM: `data/viscosity_report/report_<sample>.txt`
```
--- Iteration <N> (<timestamp>) ---
Parameters     : { ... }
Signed error   : <value> µL
Absolute error : <value> µL
```

**Step 9 — Check stop conditions**

Stop when **either** is met:

| Condition | Description |
|---|---|
| `absolute_error ≤ error_threshold` | Transfer accuracy within acceptable tolerance |
| `iteration ≥ max_iterations` | Maximum iterations reached |

**Step 10 — Suggest next aspiration volume**

Call `.suggest()` on the optimizer to get the next `{"aspiration_volume": float}` dict. Use the suggested `aspiration_volume` as the aspirate volume in the next protocol. Repeat from Step 3.

---

### Phase 3 — Completion

On stop:
- Call `driver.shutdown()` to close the serial port cleanly
- Log the best aspiration volume and best absolute error
- Save a final summary to `reports/`
- Invoke **puda-memory** to update `experiment.md`

**Step 11 — Generate PUDA report**

Use the confirmed `project_id` and `experiment_id` :
1. Extract all data related to the project with `puda project extract`.
2. Use `puda db schema` to identify the experiment tables/fields required for the report.
3. Hash the extracted experiment data used for analysis and include the hash in the report for provenance.
4. Report the best aspiration volume, signed/absolute error trend, raw/processed data paths, optimizer approach, and stop condition.

---

## Quick-Start (Programmatic)

```python
from experiments.viscosity_optimization import (
    ViscosityOptimizationExperiment, ExperimentConfig,
    LabwareConfig, ProtocolStep,
)

exp = ViscosityOptimizationExperiment(
    robot_ip="<OT2_IP>",
    balance_port="/dev/ttyUSB1",    # ask user for correct port
    data_dir="data",
)
exp.setup()   # interactive wizard — asks all inputs above
exp.run()
```

## Data Folders

| Folder | Contents |
|---|---|
| `data/workflows/` | Markdown workflow config (one per `setup()` call) |
| `data/viscosity_raw_data/` | Raw CSVs from each run |
| `data/viscosity_processed_data/` | Processed, normalised CSVs |
| `data/viscosity_report/` | Per-sample reports (`.csv` Bayesian / `.txt` LLM) |
| `reports/` | Final PUDA report artifacts generated with `puda-report` |

---

## Rules

- Always confirm OT-2 IP and balance serial port (`/dev/ttyUSB*` or `/dev/ttyACM*`) **before** generating any protocol.
- Always load both the opentrons and balance machine references from **puda-machines** before generating commands for this workflow.
- Never add `load_labware` or `load_instrument` to `protocol_steps` — they are auto-injected.
- Balance edge service (`uv run --package balance-edge python edge/balance.py`) **must be running** before connecting.
- Never ask the user to paste API keys, tokens, passwords, or other secrets into chat.
- If `llm` optimization requires credentials such as `OPENROUTER_API_KEY`, require them to be pre-configured in the local environment outside the chat before running.
- If the required LLM credential is missing, stop and tell the user to set it locally, but do not ask them to reveal the secret value and do not write the secret into prompts, config files, protocol files, or shell commands.
- Only use `get_mass()["mass_g"]` where `fresh == True`, convert it to `mass_mg = mass_g * 1000`, and discard stale readings (age ≥ 5 s).
- Call `driver.tare(wait=2.0)` at the start of each iteration before running the protocol.
- Call `driver.shutdown()` after all iterations are complete to close the serial port cleanly.
- Pick up tips sequentially from the tip rack starting at `A1`, then `A2`, `A3`, `A4`, and continue in row-major order for every later run.
- Protocol must always end with no tip attached (Opentrons sequencing rule).
- Invoke **puda-memory** after every protocol creation and run.
- **If unsure about any input, parameter, or decision — ask the user. Do not assume.**
