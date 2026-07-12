---
name: colour-mixing-optimization-methods
description: BO, LLM, and CO-HELIOS optimization approaches for colour mixing Delta E 2000 minimization and viscosity transfer-error minimization.
---

# Optimization Methods

---

## Colour Mixing — Bayesian Optimization (SOCM)

**Script**: [../../scripts/optimization_workflow/optimizers.py](../../scripts/optimization_workflow/optimizers.py)  
**Library**: `botorch` + `torch` + `gpytorch` — `pip install botorch gpytorch torch openai`

**Classes**:

| Class | Acquisition | When to use |
|---|---|---|
| `SOCM_BOEI` | `LogExpectedImprovement` (EI) | Default; balances exploration and exploitation; `xi` tunes the exploration bonus (default `0.01`) |
| `SOCM_BOLCB` | `UpperConfidenceBound` (LCB) | More explorative; useful when the Delta E 2000 landscape is uncertain or noisy |

Ask the user which class to use before initializing.

**Setup**:
- Search space: `R_vol`, `G_vol`, `B_vol`, `water_vol` in µL, normalised to `[0, 1]` internally
- **Equality constraint**: `x1 + x2 + x3 + x4 = 1` (normalised) — passed directly to `optimize_acqf` via `equality_constraints`; maps to `R_vol + G_vol + B_vol + water_vol = total_volume` in µL
- Objective: minimize Delta E 2000 (negated internally — botorch maximises)
- Surrogate: `SingleTaskGP` with Matérn 5/2 kernel, refit after every observation

**Usage**:
```python
from scripts.optimization_workflow.optimizers import SOCM_BOEI, SOCM_BOLCB

# EI — xi controls exploration bonus (default 0.01; higher = more explorative)
optimizer = SOCM_BOEI(total_volume=300.0)
optimizer = SOCM_BOEI(total_volume=300.0, xi=0.05)  # more explorative

# LCB — beta controls exploration (higher = more explorative, default 2.0)
optimizer = SOCM_BOLCB(total_volume=300.0, beta=2.0)

# Seed with x_init results
for volumes, delta_e_2000 in x_init_results:
    optimizer.observe(volumes, delta_e_2000)

# Get next suggestion each iteration
next_volumes = optimizer.suggest()  # [R_vol, G_vol, B_vol, water_vol] in µL
```

---

## Colour Mixing — LLM Optimization (SOCM)

**Script**: [../../scripts/optimization_workflow/optimizers.py](../../scripts/optimization_workflow/optimizers.py)  
**Library**: `openai` — `pip install openai`  
**Provider**: OpenRouter (`https://openrouter.ai/api/v1`)  
**API key**: set as environment variable `OPENROUTER_API_KEY`

**Class**: `SOCM_LLM` (alias: `LLMOptimizer`) — single objective (Delta E 2000).

Ask the user which model to use before initializing. Do not assume a default.

**Available models**:

| Shorthand | OpenRouter identifier |
|---|---|
| `gpt-4o` | `openai/gpt-4o` |
| `gpt-4.1` | `openai/gpt-4.1` |
| `gpt-5.1` | `openai/gpt-5.1` |
| `gpt-5.4` | `openai/gpt-5.4` |
| `claude-sonnet-4-5` | `anthropic/claude-sonnet-4-5` |
| `claude-sonnet-4.6` | `anthropic/claude-sonnet-4.6` |
| `claude-opus-4` | `anthropic/claude-opus-4` |
| `claude-opus-4.7` | `anthropic/claude-opus-4.7` |
| `gemini-3.1-pro-preview` | `google/gemini-3.1-pro-preview` |
| `gemini-2.5-pro` | `google/gemini-2.5-pro-preview` |
| `llama-4-maverick` | `meta-llama/llama-4-maverick` |
| `deepseek-r2` | `deepseek/deepseek-r2` |
| `deepseek-chat-v3` | `deepseek/deepseek-chat-v3-0324` |
| `deepseek-v3.2` | `deepseek/deepseek-v3.2` |
| `qwen3.5-plus` | `qwen/qwen3.5-plus-02-15` |
| `qwen3.6plus` | `qwen/qwen3.6-plus` |
| `qwen3-max` | `qwen/qwen3-max` |
| `glm-5.1` | `z-ai/glm-5.1` |
| `glm-4.6` | `z-ai/glm-4.6` |
| `kimi-k2.5` | `moonshotai/kimi-k2.5` |
| `kimi-k2.6` | `moonshotai/kimi-k2.6` |
| `kimi-k2-0905` | `moonshotai/kimi-k2-0905` |

**Usage**:
```python
from scripts.optimization_workflow.optimizers import LLMOptimizer, OPENROUTER_MODELS

optimizer = LLMOptimizer(
    model=OPENROUTER_MODELS["gpt-4o"],   # or any OpenRouter identifier
    target_colour=(180, 60, 40),
    total_volume=300.0,
)

# Seed with x_init results
for volumes, rgb, delta_e_2000 in x_init_results:
    optimizer.observe(volumes, rgb, delta_e_2000)

# Get next suggestion each iteration
next_volumes = optimizer.suggest()  # [R_vol, G_vol, B_vol, water_vol] in µL
```

**Rules**:
- Full history is included in every prompt — do not truncate
- Response is validated against the volume sum constraint (±1 µL tolerance) using `R_vol + G_vol + B_vol + water_vol = total_volume`; re-prompted up to `max_retries` times if invalid
- Log model name, prompt, and response in the iteration report for reproducibility

---

## Colour Mixing - CO-HELIOS Optimization (SOCM)

**Scripts**:
- [../../scripts/co_helios/co_helios_optimizer.py](../../scripts/co_helios/co_helios_optimizer.py) - public optimizer and PlannerAgent / DesignAgent / SafetyAgent chain.
- [../../scripts/co_helios/optimization.py](../../scripts/co_helios/optimization.py) - local HELIOS optimization contracts, OptimizationAgent, and decision policy.
**Shared import**: `SOCM_COHELIOS` / `COHeliosOptimizer` from [../../scripts/optimization_workflow/optimizers.py](../../scripts/optimization_workflow/optimizers.py)  
**Report helper**: `scripts.co_helios.reporting.co_helios_report_markdown_rows`

**Class**: `CoHeliosOptimizer` (aliases: `HELIOSOptimizer`, `SOCM_COHELIOS`, `COHeliosOptimizer`) - local HELIOS-style PlannerAgent -> DesignAgent -> OptimizationAgent -> SafetyAgent chain.

Use CO-HELIOS when the user wants explicit agent traceability for the optimization approach. It does not call the full HELIOS service; it implements the HELIOS agent and optimization contracts locally through `BaseAgent`, `DecisionNode`, `ColourMixingDomainKnowledge`, `OptimizationRequest`, `CandidateSuggestion`, and `OptimizationDecisionPolicy` so the PUDA workflow can run without the HELIOS web app.

The local optimization layer mirrors the parts of upstream HELIOS needed by PUDA:

| Upstream HELIOS idea | PUDA local implementation |
|---|---|
| `app.agents.optimization_agent.OptimizationAgent` | `scripts.co_helios.optimization.OptimizationAgent` |
| `app.optimization.schemas` | `OptimizationRequest`, `OptimizationObservation`, `CandidateSuggestion`, `CandidateDecision` |
| `app.optimization.decision_policy` | `OptimizationDecisionPolicy` hard-gates candidates |
| Candidate bounds and duplicate checks | Search-dimension bounds, RGBy simplex sum, and history deduplication |
| Safety hook | Delegates to the local `SafetyAgent` before a candidate can reach protocol generation |

**Usage**:
```python
from scripts.optimization_workflow.optimizers import COHeliosOptimizer

optimizer = COHeliosOptimizer(
    target_colour=(180, 60, 40),
    total_volume=300.0,
    max_rounds=12,
    batch_size=8,
    seed=42,
)

for volumes, rgb, delta_e_2000 in x_init_results:
    optimizer.observe(volumes, rgb, delta_e_2000)

suggestion = optimizer.suggest()
next_volumes = suggestion.volumes
metadata = suggestion.metadata
```

**Required report evidence**:
- `suggestion.optimizer` must be `CO_HELIOS`.
- `suggestion.metadata["agent_chain"]` must contain `PlannerAgent`, `DesignAgent`, and `SafetyAgent`.
- `suggestion.metadata["integration_chain"]` must contain `PlannerAgent`, `DesignAgent`, `OptimizationAgent`, and `SafetyAgent`.
- `suggestion.metadata["optimization"]` must include the selected strategy, convergence signal, candidate decision, and decision trace.
- Append the CO-HELIOS metadata rows from `co_helios_report_markdown_rows(suggestion)` to every optimization iteration block.
- Generate protocols only from the validated numeric `suggestion.volumes`, never from rationale text or decision metadata.

---

## Viscosity / Transfer Tuning — Bayesian Optimization (SOVH)

**Script**: [../../scripts/optimization_workflow/optimizers.py](../../scripts/optimization_workflow/optimizers.py)  
**Library**: `botorch` + `torch` + `gpytorch` — `pip install botorch gpytorch torch`

**Classes**:

| Class | Acquisition | GP target | When to use |
|---|---|---|---|
| `SOVH_EI` | `LogExpectedImprovement` (EI) | `-(signed_error²)` | Default; minimises squared transfer error; `xi` tunes exploration bonus (default `0.01`) |
| `SOVH_LCB` | `UpperConfidenceBound` (LCB) | `absolute_error_ul` | More explorative; `beta` controls exploration weight (default `1.0`) |

Backward-compatible aliases: `ViscosityBOOptimizerEI = SOVH_EI`, `ViscosityBOOptimizerLCB = SOVH_LCB`.

Ask the user which class to use before initializing.

**Setup**:
- Search space: one or more protocol parameters (e.g. `aspirate_rate`, `dispense_rate`, `volume`) with explicit `(name, min, max)` bounds
- Each parameter is normalised to `[0, 1]` internally; no equality constraint (box-bounded)
- Observations use **signed error** `actual − target` (µL); absolute error is derived automatically
- Objective: minimise absolute transfer error (GP target varies by subclass — see table above)

**Usage**:
```python
from scripts.optimization_workflow.optimizers import SOVH_EI, SOVH_LCB

param_bounds = [
    ("aspiration_volume", 10.0, 1000.0),
]

# EI — xi controls exploration bonus (default 0.01; higher = more explorative)
optimizer = SOVH_EI(param_bounds)
optimizer = SOVH_EI(param_bounds, xi=0.05)  # more explorative

# LCB — beta controls exploration weight (default 1.0; higher = more explorative)
optimizer = SOVH_LCB(param_bounds, beta=1.0)

# Record observations
optimizer.observe(
    {"aspiration_volume": 500.0},
    signed_error_mg=3.2,           # actual − target (mg)
)

# Get next suggestion
next_params = optimizer.suggest()  # {"aspiration_volume": ...}
```

---

## Viscosity / Transfer Tuning — LLM Optimization (SOVH)

**Script**: [../../scripts/optimization_workflow/optimizers.py](../../scripts/optimization_workflow/optimizers.py)  
**Library**: `openai` — `pip install openai`  
**Provider**: OpenRouter (`https://openrouter.ai/api/v1`)  
**API key**: set as environment variable `OPENROUTER_API_KEY`

**Class**: `SOVH_LLM` (alias: `ViscosityLLMOptimizer`) — single objective (absolute transfer error).

**Two prompt modes** (selected automatically from `param_bounds`):
- **Volume-only** (`param_bounds = [("volume", min, max)]`): Structured prompt with per-iteration mass, actual volume, signed error, full history, and constant flowrate. Recommended for aspiration-volume tuning.
- **Multi-parameter**: Generic prompt listing all parameter bounds and a single `absolute_error` metric.

For LLM optimization, the model must return the validated numeric suggestion and a concise report-only `reasoning` field in the same JSON object. Protocol generation uses only the numeric parameter values; the reasoning is logged for review.

**Usage**:
```python
from scripts.optimization_workflow.optimizers import SOVH_LLM, OPENROUTER_MODELS

# Volume-only mode
optimizer = SOVH_LLM(
    model=OPENROUTER_MODELS["gpt-4o"],
    param_bounds=[("volume", 10.0, 200.0)],
    target_volume_ul=100.0,
    flowrate_display="50 µL/s",
    sample_name="glycerol_30pct",   # optional, shown in prompt
)

optimizer.observe(
    {"volume": 80.0},
    absolute_error=5.0,
    signed_error_ul=-5.0,
    relative_mass_change_mg=4.95,
    relative_volume_change_uL=95.0,
)

next_params = optimizer.suggest()  # {"volume": ...}
reasoning = optimizer.last_reasoning

# Or get both explicitly in one call:
next_params, reasoning = optimizer.suggest_with_reasoning()
```

**Rules**:
- Full history is included in every prompt — do not truncate
- Response is validated against each parameter's `[min, max]` bounds, and must include non-empty `reasoning`; re-prompted up to `max_retries` times if invalid
- Required volume-only JSON shape: `{"volume": <number>, "reasoning": "<1-3 concise sentences>"}`
- For multi-parameter mode, include every numeric parameter key plus `reasoning`
- Log model name, prompt, and response in the iteration report for reproducibility
- `OPENROUTER_API_KEY` and `OPENROUTER_BASE_URL` must be set in the local environment before running
