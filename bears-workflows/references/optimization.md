---
name: colour-mixing-optimization-methods
description: BO and LLM optimization approaches for colour mixing RMSE minimization.
---

# Optimization Methods

## Bayesian Optimization (BO)

**Script**: [../scripts/optimizers.py](../scripts/optimizers.py)  
**Library**: `botorch` + `torch` + `gpytorch` — `pip install botorch gpytorch torch openai`

**Classes**:

| Class | Acquisition | When to use |
|---|---|---|
| `SOCM_BOEI` | `LogExpectedImprovement` (EI) | Default; balances exploration and exploitation; good for most cases |
| `SOCM_BOLCB` | `UpperConfidenceBound` (LCB) | More explorative; useful when the RMSE landscape is uncertain or noisy |

Ask the user which class to use before initializing.

**Setup**:
- Search space: `R_vol`, `G_vol`, `B_vol` in µL, normalised to `[0, 1]` internally
- **Equality constraint**: `x1 + x2 + x3 = 1` (normalised) — passed directly to `optimize_acqf` via `equality_constraints`; maps to `R_vol + G_vol + B_vol = total_volume` in µL
- Objective: minimize RMSE (negated internally — botorch maximises)
- Surrogate: `SingleTaskGP` with Matérn 5/2 kernel, refit after every observation

**Usage**:
```python
from scripts.optimizers import SOCM_BOEI, SOCM_BOLCB

# EI
optimizer = SOCM_BOEI(total_volume=300.0)

# LCB — beta controls exploration (higher = more explorative, default 2.0)
optimizer = SOCM_BOLCB(total_volume=300.0, beta=2.0)

# Seed with x_init results
for volumes, rmse in x_init_results:
    optimizer.observe(volumes, rmse)

# Get next suggestion each iteration
next_volumes = optimizer.suggest()  # [R_vol, G_vol, B_vol] in µL
```

---

## LLM Optimization

**Script**: [../scripts/optimizers.py](../scripts/optimizers.py)  
**Library**: `openai` — `pip install openai`  
**Provider**: OpenRouter (`https://openrouter.ai/api/v1`)  
**API key**: set as environment variable `OPENROUTER_API_KEY`

**Class**: `SOCM_LLM` (alias: `LLMOptimizer`) — single objective (RMSE).

Ask the user which model to use before initializing. Do not assume a default.

**Available models**:

| Shorthand | OpenRouter identifier |
|---|---|
| `gpt-4o` | `openai/gpt-4o` |
| `gpt-4.1` | `openai/gpt-4.1` |
| `gpt-5.1` | `openai/gpt-5.1` |
| `claude-sonnet-4-5` | `anthropic/claude-sonnet-4-5` |
| `claude-opus-4` | `anthropic/claude-opus-4` |
| `gemini-2.5-pro` | `google/gemini-2.5-pro-preview` |
| `llama-4-maverick` | `meta-llama/llama-4-maverick` |
| `deepseek-r2` | `deepseek/deepseek-r2` |
| `deepseek-v3.2` | `deepseek/deepseek-v3.2` |
| `qwen3-max` | `qwen/qwen3-max` |
| `glm-4.6` | `z-ai/glm-4.6` |
| `kimi-k2-0905` | `moonshotai/kimi-k2-0905` |

**Usage**:
```python
from scripts.optimizers import LLMOptimizer, OPENROUTER_MODELS

optimizer = LLMOptimizer(
    model=OPENROUTER_MODELS["gpt-4o"],   # or any OpenRouter identifier
    target_colour=(180, 60, 40),
    total_volume=300.0,
)

# Seed with x_init results
for volumes, rgb, rmse in x_init_results:
    optimizer.observe(volumes, rgb, rmse)

# Get next suggestion each iteration
next_volumes = optimizer.suggest()  # [R_vol, G_vol, B_vol] in µL
```

**Rules**:
- Full history is included in every prompt — do not truncate
- Response is validated against the volume sum constraint (±1 µL tolerance); re-prompted up to `max_retries` times if invalid
- Log model name, prompt, and response in the iteration report for reproducibility
