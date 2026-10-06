---
name: rsi-colour-mixing-evaluation
description: Evaluator-led recursive self-improvement for colour mixing, with a separate executor and no prescribed colour-error metric.
---

# RSI Colour Mixing Evaluation

## Evaluator/executor contract

1. The executor performs one validated experiment, processes the image, and records the executed RGBY volumes, measured RGB, target RGB, run ID, iteration, and history.
2. The executor builds an immutable request with [`rsi_handoff.py`](../../scripts/RSI%20optimization/rsi_handoff.py). It contains raw observations, not a precomputed score.
3. A separate evaluator examines the raw result and history. It selects and documents an evaluation method, evaluates the result, and either suggests one new RGBY parameter set or proposes a workflow change.
4. The evaluator returns one `rsi_colour_mixing_handoff`. The executor validates its observation hash, sequence, method declaration, fields, numeric values, and volume total.
5. The executor runs only the validated numeric suggestion and returns the new raw observation to the evaluator.

The evaluator is not restricted to a fixed metric list. For every decision, `evaluation_method` must contain:

- `name`: evaluator-selected method name
- `source`: exactly `evaluator_defined`
- `goal`: `minimize` or `maximize`
- `value`: finite numeric result for this observation
- `definition`: what the value means
- `calculation`: reproducible explanation of how it was derived
- `uses_only_observation_data`: `true`

The evaluator may change its method between iterations when it explains why. A method requiring new sensing, altered image processing, different stopping rules, or another structural change must return `decision: "propose_workflow_change"`; this is non-executable and requires explicit user approval.

## Minimal API

```python
request = build_evaluation_request(
    run_id=run_id,
    iteration=iteration,
    volumes=executed_volumes,
    measured_rgb=measured_rgb,
    target_rgb=target_rgb,
    total_volume_ul=total_volume,
    history=history,
)

validated = validate_evaluator_handoff(
    evaluator_handoff,
    expected_observation_sha256=request["observation_sha256"],
    total_volume_ul=total_volume,
    expected_next_iteration=iteration + 1,
)
```

The executor rejects invalid suggestions instead of correcting them. A new observation invalidates every older unexecuted handoff.

## Viscosity workflows

For viscosity and transfer tuning, follow [viscosity-optimization.md](viscosity-optimization.md). Its separate measurement contract is unchanged.
