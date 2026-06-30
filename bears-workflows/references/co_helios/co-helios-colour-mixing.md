---
name: co-helios-colour-mixing
description: CO-HELIOS adapter for Bears colour-mixing optimization using a PlannerAgent, DesignAgent, and SafetyAgent chain.
---

# CO-HELIOS Colour-Mixing Optimizer

CO-HELIOS adds a local multi-agent optimizer option to the existing Bears colour-mixing workflow.
It keeps the current Bears workflow responsible for Opentrons protocol generation, camera image processing, RGB extraction, Delta E 2000 scoring, reporting, and stop conditions.

## Local Layout

- `../../scripts/co_helios/co_helios_optimizer.py` - optimizer agent chain and public optimizer class.
- `../../scripts/co_helios/optimization.py` - local HELIOS optimization contracts, `OptimizationAgent`, and candidate decision policy.
- `../../scripts/co_helios/base.py` - local HELIOS-compatible `BaseAgent`, `AgentResult`, and `DecisionNode` primitives.
- `../../scripts/co_helios/domain_knowledge.py` - colour-mixing domain rules used by planner, design, and safety agents.
- `../../scripts/co_helios/reporting.py` - helper for appending mandatory CO-HELIOS report rows.
- `../../scripts/co_helios/workflow.py` - convenience imports for existing image-processing and metric helpers.
- `../../scripts/optimization_workflow/build_colour_mixing_protocol.py` - Opentrons protocol generation.
- `../../scripts/optimization_workflow/image_processing.py` - plate image correction and well RGB extraction.
- `../../scripts/optimization_workflow/metric.py` - Delta E 2000 and RGBy volume validation.

## Agent Contract

CO-HELIOS uses the same public optimizer shape as the existing colour-mixing optimizers:

1. Call `observe(volumes, mixed_rgb, delta_e_2000)` after each completed run.
2. Call `suggest()` to get the next validated `[R_vol, G_vol, B_vol, water_vol]` vector.
3. Use only `suggestion.volumes` for protocol generation.
4. Store `suggestion.metadata` in the report if agent decision traceability is needed.

The agents follow the HELIOS pattern from `https://github.com/SissiFeng/HELIOS/tree/main`: they inherit from `BaseAgent`, emit `DecisionNode` dictionaries, and use domain knowledge instead of hard-coded report-only labels. This local adapter does not require the full HELIOS web service to be running.

The optimizer output includes:

| Field | Meaning |
|---|---|
| `volumes` | Four validated microliter volumes in `[R, G, B, water]` order |
| `optimizer` | `"CO_HELIOS"` |
| `llm_reasoning` | Short local rationale for the report; no protocol logic should depend on it |
| `metadata.agent_chain` | Explicit `["PlannerAgent", "DesignAgent", "SafetyAgent"]` trace marker for the core agent chain |
| `metadata.integration_chain` | Explicit `["PlannerAgent", "DesignAgent", "OptimizationAgent", "SafetyAgent"]` trace marker for the full PUDA integration |
| `metadata.domain_knowledge` | Colour-mixing safety policy from `domain_knowledge.py` |
| `metadata.agent_runs` | Per-agent success state, trace id, duration, and decision tree |
| `metadata.plan` | Planner phase, strategy, resource estimate, and notes |
| `metadata.planner_decisions` | Budget and strategy decision nodes |
| `metadata.design_decisions` | Candidate generation confidence decision nodes |
| `metadata.candidate_confidence` | Per-candidate confidence summaries |
| `metadata.optimization` | OptimizationAgent strategy, convergence signal, decision, and candidate suggestion contract |
| `metadata.optimization_decisions` | OptimizationAgent candidate-selection decision nodes |
| `metadata.safety` | Safety decision report |
| `metadata.safety_decisions` | Safety preflight and escalation decision nodes |
| `metadata.rejected_candidates` | Candidates rejected before the approved suggestion |

## PlannerAgent

`PlannerAgent` converts the current optimization state into a one-round plan.

Inputs:

| Input | Meaning |
|---|---|
| `completed_rounds` | Number of completed optimization observations |
| `n_observations` | Number of usable history rows |
| `max_rounds` | Maximum allowed optimization rounds |
| `batch_size` | Number of candidate mixes to generate before safety selection |

Outputs:

| Output | Meaning |
|---|---|
| `round_number` | Next round number |
| `phase` | `exploration`, `exploitation`, or `refinement` |
| `strategy` | `space_filling`, `best_guided`, or `local_refinement` |
| `resource_estimate` | Tips, instruments, and approximate run duration |
| `decision_nodes` | Budget and strategy audit records |

Planning policy:

- If fewer than three observations exist, use `exploration` with `space_filling`.
- In the first 20% of the round budget, use `exploration`.
- From 20% to 80% of the round budget, use `exploitation` with `best_guided`.
- In the final 20% of the round budget, use `refinement` with `local_refinement`.
- Resource estimate assumes four component transfers per candidate: red, green, blue, and water.

## DesignAgent

`DesignAgent` generates candidate `(R, G, B, water)` mixes from the plan and experiment history.

Candidate policies:

| Strategy | Candidate behavior |
|---|---|
| `space_filling` | Generates simplex-wide anchor mixes and random RGBy simplex samples if more candidates are needed |
| `best_guided` | Starts near the best observed Delta E 2000 mix and adjusts dye/water directionally using target-vs-measured RGB |
| `local_refinement` | Uses smaller jitter around the best observed mix |

Confidence metadata:

- Space-filling exploration is marked as low-confidence because it intentionally searches broad unexplored regions.
- Best-guided and local-refinement candidates are marked as usable-confidence because they exploit observed history.
- Confidence metadata is advisory report data only; safety validation is still mandatory.

## SafetyAgent

`SafetyAgent` is the final gate before any optimizer candidate can be returned.

Safety checks:

- Candidate must contain exactly four values: red, green, blue, water.
- Every value must be numeric and finite.
- Every value must be non-negative.
- Volume sum must match `total_volume` within tolerance.
- No component may exceed the configured maximum component fraction.

Safety thresholds:

| Threshold | Behavior |
|---|---|
| `safety_score >= 0.8` | Auto-approved if no violations exist |
| `0.5 <= safety_score < 0.8` | Marked as requiring review |
| `safety_score < 0.5` | Vetoed |

For the current colour-mixing adapter, any explicit violation vetoes the candidate.
The safety gate uses fine granularity, meaning every candidate is checked independently.

## OptimizationAgent and Decision Policy

`OptimizationAgent` is the local PUDA version of the upstream HELIOS optimization agent and `app/optimization` decision layer.
It consumes the candidate batch from `DesignAgent`, converts each `[R, G, B, water]` vector into named HELIOS-style parameters, ranks candidates against the best historical Delta E 2000 observation, and applies a hard decision policy before the final `SafetyAgent` handoff.

Hard gates:

- Candidate must contain exactly `red`, `green`, `blue`, and `water`.
- Every parameter must be numeric, finite, and inside the search-space bounds.
- The four parameters must sum to `total_volume` within tolerance.
- Candidates already present in history are rejected as duplicates.
- A delegated `SafetyAgent` check must approve the candidate.

The optimizer records the selected strategy, convergence signal, decision trace, rejected candidates, and selected candidate in `suggestion.metadata["optimization"]`.

## Usage

```python
from scripts.co_helios.co_helios_optimizer import CoHeliosOptimizer

optimizer = CoHeliosOptimizer(
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

`next_volumes` is always `[R_vol, G_vol, B_vol, water_vol]` in microliters.

## Workflow Integration

Use CO-HELIOS only as the optimizer selection step.
The rest of the Bears colour-mixing workflow remains unchanged:

1. Generate or collect `x_init` mixes.
2. Process captured plate images with `run_pipeline(...)`.
3. Calculate Delta E 2000 for every active well.
4. Record observations with `optimizer.observe(...)`.
5. Get the next candidate with `optimizer.suggest()`.
6. Validate `suggestion.volumes` again with `validate_rgby_volumes(...)`.
7. Generate the Opentrons protocol with `build_colour_mixing_protocol(...)`.
8. Append planner, design, confidence, and safety metadata to the report.
9. Include optimization decision metadata from `suggestion.metadata["optimization"]`.

## Required Validation Before Protocol Generation

- Every target mix, seed mix, optimizer suggestion, protocol row, and report row must include red, green, blue, and water.
- Validate `R + G + B + water = total_volume` before protocol generation.
- Reject any candidate that omits water or returns only RGB dye volumes.
- Do not use decision metadata, rationale text, or confidence labels as liquid-handling inputs.
- Generate protocols only from the validated numeric `suggestion.volumes` list.

## Report Fields

When CO-HELIOS is used, include these rows in each iteration block:

| Report row | Source |
|---|---|
| Optimizer | `suggestion.optimizer` |
| Planner phase | `suggestion.metadata["plan"]["phase"]` |
| Planner strategy | `suggestion.metadata["plan"]["strategy"]` |
| Planner resource estimate | `suggestion.metadata["plan"]["resource_estimate"]` |
| Candidate confidence | `suggestion.metadata["candidate_confidence"]` |
| Optimization strategy | `suggestion.metadata["optimization"]["strategy_selected"]` |
| Optimization convergence signal | `suggestion.metadata["optimization"]["convergence_signal"]` |
| Optimization decision trace | `suggestion.metadata["optimization"]["decision_trace"]` |
| Safety score | `suggestion.metadata["safety"]["safety_score"]` |
| Safety violations | `suggestion.metadata["safety"]["violations"]` |
| Agent decision trace | `planner_decisions`, `design_decisions`, and `safety_decisions` |
