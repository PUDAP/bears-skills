"""Validated handoffs for recursive self-improvement colour mixing.

The evaluator agent reasons about observations and proposes the next RGBy
volumes.  The executor agent validates and executes those volumes, but never
changes them silently.  This module defines the JSON boundary between them; it
does not call an LLM or operate laboratory hardware.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "2.0"
COMPONENT_KEYS = ("red_ul", "green_ul", "blue_ul", "water_ul")
HANDOFF_TYPE = "rsi_colour_mixing_handoff"


class HandoffValidationError(ValueError):
    """Raised when an evaluator/executor handoff is unsafe or malformed."""


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HandoffValidationError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise HandoffValidationError(f"{field} must be finite")
    return number


def _rgb(value: Any, field: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 3:
        raise HandoffValidationError(f"{field} must contain exactly three RGB values")
    result = [_finite_number(channel, f"{field}[{index}]") for index, channel in enumerate(value)]
    if any(channel < 0 or channel > 255 for channel in result):
        raise HandoffValidationError(f"{field} values must be between 0 and 255")
    return result


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_evaluation_method(method: Any) -> dict[str, Any]:
    """Validate the evaluator's self-declared assessment method."""
    if not isinstance(method, Mapping):
        raise HandoffValidationError("evaluation_method must be an evaluator-defined object")
    required = {"name", "source", "goal", "value", "definition", "calculation", "uses_only_observation_data"}
    if set(method) != required:
        raise HandoffValidationError(
            f"evaluator-defined evaluation_method must contain exactly {tuple(sorted(required))}"
        )
    name = method.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HandoffValidationError("evaluation method name must be non-empty")
    if method.get("source") != "evaluator_defined":
        raise HandoffValidationError("evaluation method source must be evaluator_defined")
    if method.get("goal") not in {"minimize", "maximize"}:
        raise HandoffValidationError("evaluation method goal must be minimize or maximize")
    if method.get("uses_only_observation_data") is not True:
        raise HandoffValidationError(
            "a method requiring new data or processing must be proposed as a workflow change"
        )
    definition = method.get("definition")
    calculation = method.get("calculation")
    if not isinstance(definition, str) or not definition.strip():
        raise HandoffValidationError("evaluation method definition must be non-empty")
    if not isinstance(calculation, str) or not calculation.strip():
        raise HandoffValidationError("evaluation method calculation must be non-empty")
    return {
        "name": name.strip(),
        "source": "evaluator_defined",
        "goal": method["goal"],
        "value": _finite_number(method.get("value"), "evaluation_method.value"),
        "definition": definition.strip(),
        "calculation": calculation.strip(),
        "uses_only_observation_data": True,
    }


def build_evaluation_request(
    *,
    run_id: str,
    iteration: int,
    volumes: Sequence[float],
    measured_rgb: Sequence[float],
    target_rgb: Sequence[float],
    total_volume_ul: float,
    history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Create the immutable observation passed from executor to evaluator."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise HandoffValidationError("run_id must be a non-empty string")
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        raise HandoffValidationError("iteration must be a non-negative integer")
    total = _finite_number(total_volume_ul, "total_volume_ul")
    if total <= 0:
        raise HandoffValidationError("total_volume_ul must be greater than zero")
    if len(volumes) != 4:
        raise HandoffValidationError("volumes must contain red, green, blue, and water")
    numeric_volumes = [_finite_number(value, f"volumes[{index}]") for index, value in enumerate(volumes)]
    if any(value < 0 for value in numeric_volumes):
        raise HandoffValidationError("volumes must be non-negative")
    if abs(sum(numeric_volumes) - total) > 1.0:
        raise HandoffValidationError("volumes must sum to total_volume_ul within +/-1 uL")

    measured = _rgb(measured_rgb, "measured_rgb")
    target = _rgb(target_rgb, "target_rgb")
    observation = {
        "run_id": run_id.strip(),
        "iteration": iteration,
        "volumes_ul": dict(zip(COMPONENT_KEYS, numeric_volumes)),
        "measured_rgb": measured,
        "target_rgb": target,
        "total_volume_ul": total,
    }

    request = {
        "schema_version": SCHEMA_VERSION,
        "type": "rsi_evaluation_request",
        "roles": {"from": "executor", "to": "evaluator"},
        "observation": observation,
        "history": list(history),
    }
    request["observation_sha256"] = _canonical_digest(observation)
    return request


def validate_evaluator_handoff(
    payload: Mapping[str, Any],
    *,
    expected_observation_sha256: str,
    total_volume_ul: float,
    expected_next_iteration: int,
    tolerance_ul: float = 1.0,
) -> dict[str, Any]:
    """Validate and normalize an evaluator suggestion before execution."""
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise HandoffValidationError(f"schema_version must be {SCHEMA_VERSION}")
    if payload.get("type") != HANDOFF_TYPE:
        raise HandoffValidationError(f"type must be {HANDOFF_TYPE}")
    if payload.get("roles") != {"from": "evaluator", "to": "executor"}:
        raise HandoffValidationError("roles must be evaluator -> executor")
    if payload.get("observation_sha256") != expected_observation_sha256:
        raise HandoffValidationError("handoff does not match the latest observation")
    decision = payload.get("decision")
    if decision not in {"execute_next_iteration", "propose_workflow_change"}:
        raise HandoffValidationError(
            "decision must be execute_next_iteration or propose_workflow_change"
        )
    if payload.get("next_iteration") != expected_next_iteration:
        raise HandoffValidationError("next_iteration is missing, stale, or out of sequence")

    reasoning = payload.get("evaluation")
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise HandoffValidationError("evaluation must be a non-empty explanation")
    method = _validate_evaluation_method(payload.get("evaluation_method"))

    workflow_change = payload.get("workflow_change")
    if not isinstance(workflow_change, Mapping):
        raise HandoffValidationError("workflow_change must be an object")
    action = workflow_change.get("action")
    if decision == "propose_workflow_change":
        if action != "propose":
            raise HandoffValidationError("workflow-change decisions require action=propose")
        proposal = workflow_change.get("proposal")
        rationale = workflow_change.get("rationale")
        if not isinstance(proposal, str) or not proposal.strip():
            raise HandoffValidationError("workflow change proposal must be non-empty")
        if not isinstance(rationale, str) or not rationale.strip():
            raise HandoffValidationError("workflow change rationale must be non-empty")
        if workflow_change.get("requires_user_approval") is not True:
            raise HandoffValidationError("workflow changes must require user approval")
        return {
            "schema_version": SCHEMA_VERSION,
            "type": HANDOFF_TYPE,
            "roles": {"from": "evaluator", "to": "executor"},
            "observation_sha256": expected_observation_sha256,
            "decision": decision,
            "next_iteration": expected_next_iteration,
            "evaluation_method": method,
            "evaluation": reasoning.strip(),
            "workflow_change": {
                "action": "propose",
                "proposal": proposal.strip(),
                "rationale": rationale.strip(),
                "requires_user_approval": True,
            },
            "executable": False,
        }

    if action != "none" or set(workflow_change) != {"action"}:
        raise HandoffValidationError(
            "executable handoffs cannot change the workflow; submit a proposal first"
        )
    suggestion = payload.get("suggestion")
    if not isinstance(suggestion, Mapping) or set(suggestion) != set(COMPONENT_KEYS):
        raise HandoffValidationError(f"suggestion must contain exactly {COMPONENT_KEYS}")

    normalized = {
        key: _finite_number(suggestion[key], f"suggestion.{key}") for key in COMPONENT_KEYS
    }
    if any(value < 0 for value in normalized.values()):
        raise HandoffValidationError("suggested volumes must be non-negative")
    total = _finite_number(total_volume_ul, "total_volume_ul")
    tolerance = _finite_number(tolerance_ul, "tolerance_ul")
    if tolerance < 0 or abs(sum(normalized.values()) - total) > tolerance:
        raise HandoffValidationError(
            f"suggested volumes must sum to {total:.3f} uL within +/-{tolerance:.3f} uL"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "type": HANDOFF_TYPE,
        "roles": {"from": "evaluator", "to": "executor"},
        "observation_sha256": expected_observation_sha256,
        "decision": "execute_next_iteration",
        "next_iteration": expected_next_iteration,
        "evaluation_method": method,
        "evaluation": reasoning.strip(),
        "suggestion": normalized,
        "workflow_change": {"action": "none"},
        "executable": True,
    }


def evaluator_handoff_template(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact shape an evaluator agent must fill and return."""
    observation = request.get("observation", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "type": HANDOFF_TYPE,
        "roles": {"from": "evaluator", "to": "executor"},
        "observation_sha256": request.get("observation_sha256"),
        "decision": "execute_next_iteration",
        "next_iteration": int(observation.get("iteration", 0)) + 1,
        "evaluation_method": {
            "name": "evaluator_selected_method",
            "source": "evaluator_defined",
            "goal": "minimize",
            "value": 0.0,
            "definition": "Define what this assessment measures for the current evidence.",
            "calculation": "Explain how the value was derived from the observation and history.",
            "uses_only_observation_data": True,
        },
        "evaluation": "Explain the result, trend, and why this experiment is informative.",
        "suggestion": {key: 0.0 for key in COMPONENT_KEYS},
        "workflow_change": {"action": "none"},
    }


def _load_json(path: str) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    template_parser = subparsers.add_parser("template", help="Create an evaluator response template")
    template_parser.add_argument("request")

    validate_parser = subparsers.add_parser("validate", help="Validate an evaluator handoff")
    validate_parser.add_argument("request")
    validate_parser.add_argument("handoff")

    args = parser.parse_args()
    request = _load_json(args.request)
    if args.command == "template":
        result = evaluator_handoff_template(request)
    else:
        observation = request["observation"]
        result = validate_evaluator_handoff(
            _load_json(args.handoff),
            expected_observation_sha256=request["observation_sha256"],
            total_volume_ul=observation["total_volume_ul"],
            expected_next_iteration=observation["iteration"] + 1,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
