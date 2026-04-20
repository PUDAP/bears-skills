---
name: viscosity-optimization
description: Optimize liquid handling parameters (flow rate, delay, offset) for viscous fluids on an Opentrons OT-2 using gravimetric feedback from a PUDAP Arduino-based mass balance (Linux serial), driven by Bayesian Optimization (LCB or EI) or an LLM via OpenRouter.
---

# Viscosity Optimization

Iteratively tune Opentrons OT-2 protocol parameters to minimize the transfer error (µL) for viscous liquids, using real-time gravimetric feedback from an Arduino-based mass balance and BO or LLM optimization.

## Required Skills

Invoke these skills before generating any commands:
- **puda-machines** → opentrons machine (liquid handling commands, labware)
- **puda-protocol** → protocol generation and execution
- **puda-memory** → update `experiment.md` after every protocol creation and run

## Required Hardware

- **Opentrons OT-2** — reachable on local network (confirm IP before starting)
- **Arduino-based mass balance** — connected via Linux USB serial (`/dev/ttyUSB0` or `/dev/ttyACM0`)

## Optimization Approaches

Ask the user which approach to use if not specified:

| Approach | Class | When to use |
|---|---|---|
| **Bayesian LCB (SO)** | `ViscositySOBOOptimizerLCB` | Good default; one scalar objective (e.g. abs error) |
| **Bayesian EI (SO)** | `ViscositySOBOOptimizerEI` | Noisy observations or tight iteration budget |
| **LLM (single objective)** | `ViscosityLLMSingleObjectiveOptimizer` (alias `ViscosityLLMOptimizer`) | One primary metric; volume-tuning prompt when optimising `volume` alone |
| **LLM (multi-objective)** | `ViscosityLLMMultiObjectiveOptimizer` | Several competing objectives per iteration; trade-offs in prompt |
---

## Workflow

### Phase 1 — Initialization

**Step 1 — Inputs (ask user before proceeding)**

Collect all of the following before starting. Do not proceed until every value is confirmed.

**a) Approach**

| Input | Options |
|---|---|
| Optimization approach | `bayes_lcb`, `bayes_ei`, or `llm` |
| If LLM: OpenRouter model ID | e.g. `"openai/gpt-4o"` |

If `llm` is selected, any required credential such as `OPENROUTER_API_KEY` must already be configured in the local environment outside the chat before running the workflow. Do not ask the user to paste the API key into chat.

**b) Sample and volumes**

| Input | Description |
|---|---|
| Sample name | String identifier (e.g. `"glycerol_50pct"`) |
| Initial volume | µL used in each protocol run |
| Target volume | µL expected to actually transfer |
| Liquid density | g/mL (use `1.0` for water) |

**c) Measurement**

| Input | Description |
|---|---|
| Measurement phase | `"aspirate"` or `"dispense"` — which phase the balance records |
| Outlier threshold | Weight readings (g) below this value are discarded |

**d) Stop conditions**

| Input | Description |
|---|---|
| Max iterations | Upper bound on optimization iterations |
| Error threshold | Stop when absolute error ≤ this value in µL |

**e) Labware and pipette** — for each of source, destination, tip rack:
- Variable name, labware load-name, deck slot (1–11), well (e.g. `"A1"`)

For the pipette:
- Variable name, instrument type, mount (`"left"` or `"right"`)

> `load_labware` and `load_instrument` are **injected automatically** — do not add them to the protocol steps.

**f) Protocol steps**

Ordered list of Opentrons commands. Any string parameter value that exactly matches a search parameter name is substituted with the optimizer's suggested float at runtime.

Common optimizable parameter names:

| Name | Effect |
|---|---|
| `aspirate_rate` | Aspirate flow rate (µL/s) |
| `dispense_rate` | Dispense flow rate (µL/s) |
| `blow_out_rate` | Blow-out flow rate (µL/s) |
| `aspirate_offset` | Aspirate height from well bottom (mm) |
| `dispense_offset` | Dispense height from well bottom (mm) |
| `delay_seconds` | Delay duration (s) |

**g) Search space** — for each parameter to optimize:
- Name (must match string used in protocol steps), min value, max value, initial value

**h) Balance serial port** — confirm with user:
- Linux device path, e.g. `/dev/ttyUSB0` or `/dev/ttyACM0`
- Run `ls /dev/tty{USB,ACM}*` to discover available ports

**Step 2 — Hardware connection**

Confirm the OT-2 IP and balance serial port from the user. Start the balance edge service, then connect:

```bash
uv run --package balance-edge python edge/balance.py
```

```python
exp = ViscosityOptimizationExperiment(
    robot_ip="<OT2_IP>",
    balance_port="<SERIAL_PORT>",   # e.g. "/dev/ttyUSB1"
    data_dir="data",
)
exp.connect()   # raises immediately if OT-2 or balance is unreachable
```

---

### Phase 2 — Per-Iteration Loop

**Step 3 — Generate and run protocol**

Build the protocol with current optimizer-suggested parameter values and execute on the OT-2. The balance is tared (`driver.tare(wait=2.0)`) at the start of every iteration for a fresh zero baseline.

**Step 4 — Collect concurrent data**

During the run, two concurrent threads record:
- Balance readings at **4 Hz** — reads `get_mass()["mass_g"]` with `timestamp`
- OT-2 run status at **2 Hz** — `ot2_command`, `ot2_status`

Only readings where `get_mass()["fresh"] == True` (age < 5 s) are considered valid.

Raw data is saved as:
```
data/viscosity_raw_data/<sample>_iter<NNN>_<YYYYMMDD_HHMMSS>.csv
```

**Step 5 — Process data**

The raw CSV is processed:
1. Strip apostrophes from serial output
2. Remove outlier rows where `mass_g` is below `outlier_threshold`
3. Forward-fill OT-2 command labels onto balance rows
4. Slice to the `measurement_phase` window only
5. Normalise `Time` and `Weight` to start at 0

Processed data is saved to:
```
data/viscosity_processed_data/<same filename>.csv
```

**Step 6 — Compute transfer error**

```
measured_vol_µL = (final_weight_g / liquid_density) × 1000
signed_error    = measured_vol_µL − target_volume_µL
absolute_error  = |signed_error|
```

Positive signed error = over-transfer. Negative = under-transfer.

**Step 7 — Update optimizer**

For Bayesian SOBO in [`scripts/optimizers.py`](../scripts/optimizers.py), call ``observe(params, signed_error_ul, absolute_error_ul=...)`` (``absolute_error_ul`` defaults to ``|signed_error_ul|``). The surrogate uses signed error (EI: fit on ``-(signed_error_ul²)`` toward zero error; LCB: fit on absolute error with ``UpperConfidenceBound(..., maximize=False)``).

**Step 8 — Save iteration report**

Append one row/block to the report file after every iteration.

For Bayesian: `data/viscosity_report/report_<sample>.csv`
```
iteration, timestamp, approach, signed_error_ul, abs_error_ul, <param1>, <param2>, ...
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

**Step 10 — Suggest next parameters**

Call `.suggest()` on the optimizer to get the next `{param_name: float}` dict. Use these values to generate the next protocol. Repeat from Step 3.

---

### Phase 3 — Completion

On stop:
- Call `driver.shutdown()` to close the serial port cleanly
- Log the best parameters and best absolute error
- Save a final summary to `logs/`
- Invoke **puda-memory** to update `experiment.md`

---

## Quick-Start (Programmatic)

```python
from experiments.viscosity_optimization import (
    ViscosityOptimizationExperiment, ExperimentConfig,
    LabwareConfig, ProtocolStep, SearchParam,
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

---

## Rules

- Always confirm OT-2 IP and balance serial port (`/dev/ttyUSB*` or `/dev/ttyACM*`) **before** generating any protocol.
- Never add `load_labware` or `load_instrument` to `protocol_steps` — they are auto-injected.
- Balance edge service (`uv run --package balance-edge python edge/balance.py`) **must be running** before connecting.
- Never ask the user to paste API keys, tokens, passwords, or other secrets into chat.
- If `llm` optimization requires credentials such as `OPENROUTER_API_KEY`, require them to be pre-configured in the local environment outside the chat before running.
- If the required LLM credential is missing, stop and tell the user to set it locally, but do not ask them to reveal the secret value and do not write the secret into prompts, config files, protocol files, or shell commands.
- Only use `get_mass()["mass_g"]` where `fresh == True` — discard stale readings (age ≥ 5 s).
- Call `driver.tare(wait=2.0)` at the start of each iteration before running the protocol.
- Call `driver.shutdown()` after all iterations are complete to close the serial port cleanly.
- Protocol must always end with no tip attached (Opentrons sequencing rule).
- Invoke **puda-memory** after every protocol creation and run.
- **If unsure about any input, parameter, or decision — ask the user. Do not assume.**
