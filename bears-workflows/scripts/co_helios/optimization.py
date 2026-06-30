"""Local HELIOS optimization contracts for PUDA colour-mixing workflows.

The upstream HELIOS ``app.optimization`` package provides provider schemas,
candidate pooling, decision policy, and provenance around an optimization
suggestion. This module keeps the same responsibilities in a small synchronous
form that can run inside Bears workflows without the HELIOS web application.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .base import DecisionNode


SafetyCheck = Callable[[list[float]], tuple[bool, list[str], float]]


@dataclass(frozen=True)
class SearchDimension:
    """One numeric search-space dimension."""

    param_name: str
    min_value: float
    max_value: float
    primitive: str = "robot.aspirate_dispense"


@dataclass(frozen=True)
class OptimizationObservation:
    """Historical optimizer observation used for deduplication and scoring."""

    params: dict[str, float]
    objective_value: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OptimizationRequest:
    """Self-contained request for a local HELIOS optimization round."""

    campaign_id: str
    dimensions: tuple[SearchDimension, ...]
    observations: tuple[OptimizationObservation, ...]
    objective_name: str = "delta_e_2000"
    direction: str = "minimize"
    n: int = 1
    round_index: int = 0
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSuggestion:
    """Candidate batch emitted by DesignAgent and consumed by the policy."""

    candidates: tuple[dict[str, float], ...]
    algorithm: str
    source: str
    confidence: float = 0.5
    rationale: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)
    per_candidate: tuple[dict[str, Any], ...] = ()
    seed: int | None = None


@dataclass(frozen=True)
class CandidateDecision:
    """Optimization decision-policy verdict."""

    accepted: bool
    final_candidates: tuple[dict[str, float], ...] = ()
    rejected: tuple[dict[str, Any], ...] = ()
    rejection_reasons: tuple[str, ...] = ()
    requires_human_review: bool = False
    decision_trace: tuple[str, ...] = ()


@dataclass(frozen=True)
class OptimizationOutput:
    """Output from the local OptimizationAgent."""

    candidates: tuple[dict[str, float], ...]
    strategy_selected: str
    strategy_rationale: str
    convergence_signal: float
    suggestion: CandidateSuggestion
    decision: CandidateDecision
    decision_nodes: list[dict[str, Any]] = field(default_factory=list)


def volumes_to_params(volumes: list[float]) -> dict[str, float]:
    """Convert ``[R, G, B, water]`` volumes to named HELIOS-style params."""

    if len(volumes) != 4:
        raise ValueError(f"Expected 4 volumes, got {len(volumes)}")
    return {
        "red": float(volumes[0]),
        "green": float(volumes[1]),
        "blue": float(volumes[2]),
        "water": float(volumes[3]),
    }


def params_to_volumes(params: dict[str, Any]) -> list[float]:
    """Convert named params back to Bears workflow volume order."""

    return [
        float(params["red"]),
        float(params["green"]),
        float(params["blue"]),
        float(params["water"]),
    ]


def _signature(candidate: dict[str, Any], ndigits: int = 6) -> tuple[tuple[str, Any], ...]:
    items: list[tuple[str, Any]] = []
    for key in sorted(candidate):
        value = candidate[key]
        if isinstance(value, float):
            value = round(value, ndigits)
        items.append((key, value))
    return tuple(items)


def _dimension_by_name(dimensions: tuple[SearchDimension, ...]) -> dict[str, SearchDimension]:
    return {dim.param_name: dim for dim in dimensions}


class OptimizationDecisionPolicy:
    """HELIOS-style authority over concrete colour-mixing candidates.

    The policy performs the hard gates from upstream HELIOS in local form:
    search-space bounds, duplicate rejection, simplex total-volume validation,
    and delegated SafetyAgent checks.
    """

    def __init__(
        self,
        *,
        total_volume: float,
        tolerance_ul: float = 1.0,
        safety_check: SafetyCheck | None = None,
    ) -> None:
        self.total_volume = float(total_volume)
        self.tolerance_ul = float(tolerance_ul)
        self._safety_check = safety_check

    def evaluate(
        self,
        suggestion: CandidateSuggestion,
        request: OptimizationRequest,
    ) -> CandidateDecision:
        dims = _dimension_by_name(request.dimensions)
        seen = {_signature(observation.params) for observation in request.observations}
        accepted: list[dict[str, float]] = []
        rejected: list[dict[str, Any]] = []
        reasons: list[str] = []
        trace: list[str] = [
            f"evaluating {len(suggestion.candidates)} candidate(s) from "
            f"{suggestion.source}:{suggestion.algorithm}"
        ]

        for candidate in suggestion.candidates:
            reason = self._gate(candidate, dims, seen)
            if reason is not None:
                rejected.append(dict(candidate))
                reasons.append(reason)
                trace.append(f"rejected {candidate}: {reason}")
                continue
            accepted.append(dict(candidate))
            trace.append(f"accepted {candidate}")
            if len(accepted) >= request.n:
                break

        requires_human_review = not accepted
        if requires_human_review:
            trace.append("no executable candidate -> escalating for human review")

        decision_node = DecisionNode(
            id="optimization_policy",
            label="Optimization candidate policy",
            options=["accepted", "requires_review"],
            selected="accepted" if accepted else "requires_review",
            reason=f"{len(accepted)} accepted, {len(rejected)} rejected",
            outcome="; ".join(reasons[:3]) if reasons else "candidate ready for safety handoff",
        )
        trace.append(f"decision_node={decision_node.to_dict()}")

        return CandidateDecision(
            accepted=bool(accepted),
            final_candidates=tuple(accepted),
            rejected=tuple(rejected),
            rejection_reasons=tuple(reasons),
            requires_human_review=requires_human_review,
            decision_trace=tuple(trace),
        )

    def _gate(
        self,
        candidate: dict[str, Any],
        dimensions: dict[str, SearchDimension],
        seen: set[tuple[tuple[str, Any], ...]],
    ) -> str | None:
        if set(candidate) != set(dimensions):
            missing = sorted(set(dimensions) - set(candidate))
            extra = sorted(set(candidate) - set(dimensions))
            return f"parameter mismatch: missing={missing}, extra={extra}"

        numeric: dict[str, float] = {}
        for name, dim in dimensions.items():
            try:
                value = float(candidate[name])
            except (TypeError, ValueError):
                return f"{name} is not numeric"
            if not math.isfinite(value):
                return f"{name} is not finite"
            if value < dim.min_value - self.tolerance_ul:
                return f"{name} below bounds ({value} < {dim.min_value})"
            if value > dim.max_value + self.tolerance_ul:
                return f"{name} above bounds ({value} > {dim.max_value})"
            numeric[name] = min(dim.max_value, max(dim.min_value, value))

        total = sum(numeric.values())
        if abs(total - self.total_volume) > self.tolerance_ul:
            return f"simplex sum {total:.3f} uL != {self.total_volume:.3f} uL"

        sig = _signature(numeric)
        if sig in seen:
            return "duplicate of a prior or already-accepted point"

        if self._safety_check is not None:
            allowed, violations, _score = self._safety_check(params_to_volumes(numeric))
            if not allowed:
                return "failed SafetyAgent check: " + "; ".join(violations)

        seen.add(sig)
        return None


class OptimizationAgent:
    """Local optimization agent for strategy/ranking/policy arbitration."""

    name = "optimization_agent"
    description = "HELIOS-style candidate arbitration for PUDA colour mixing"
    layer = "L2"

    def __init__(
        self,
        *,
        total_volume: float,
        tolerance_ul: float = 1.0,
        safety_check: SafetyCheck | None = None,
    ) -> None:
        self.policy = OptimizationDecisionPolicy(
            total_volume=total_volume,
            tolerance_ul=tolerance_ul,
            safety_check=safety_check,
        )

    def run(
        self,
        *,
        request: OptimizationRequest,
        candidate_volumes: list[list[float]],
        strategy: str,
        confidence: list[dict[str, Any]] | None = None,
    ) -> OptimizationOutput:
        ranked = self._rank_candidates(candidate_volumes, request)
        suggestion = CandidateSuggestion(
            candidates=tuple(volumes_to_params(volumes) for volumes in ranked),
            algorithm=strategy,
            source="local_design_agent",
            confidence=self._mean_confidence(confidence),
            rationale=f"DesignAgent generated candidates using {strategy}",
            diagnostics={
                "candidate_count": len(candidate_volumes),
                "ranked_count": len(ranked),
                "trace_id": uuid.uuid4().hex[:12],
            },
            per_candidate=tuple(confidence or ()),
        )
        decision = self.policy.evaluate(suggestion, request)
        node = DecisionNode(
            id="optimization_agent_selection",
            label="OptimizationAgent selection",
            options=["candidate_selected", "no_candidate"],
            selected="candidate_selected" if decision.accepted else "no_candidate",
            reason=f"strategy={strategy}, confidence={suggestion.confidence:.2f}",
            outcome=f"{len(decision.final_candidates)} final candidate(s)",
        )
        return OptimizationOutput(
            candidates=decision.final_candidates,
            strategy_selected=strategy,
            strategy_rationale=suggestion.rationale,
            convergence_signal=self._convergence_signal(request),
            suggestion=suggestion,
            decision=decision,
            decision_nodes=[node.to_dict()],
        )

    @staticmethod
    def _mean_confidence(confidence: list[dict[str, Any]] | None) -> float:
        if not confidence:
            return 0.5
        values = []
        for item in confidence:
            try:
                values.append(float(item.get("confidence", 0.5)))
            except (TypeError, ValueError):
                continue
        if not values:
            return 0.5
        return max(0.0, min(1.0, sum(values) / len(values)))

    @staticmethod
    def _rank_candidates(
        candidate_volumes: list[list[float]],
        request: OptimizationRequest,
    ) -> list[list[float]]:
        if not request.observations:
            return list(candidate_volumes)

        best = min(request.observations, key=lambda row: row.objective_value)
        best_volumes = params_to_volumes(best.params)
        seen = {_signature(observation.params) for observation in request.observations}

        def score(volumes: list[float]) -> tuple[int, float]:
            params = volumes_to_params(volumes)
            repeat_penalty = 1 if _signature(params) in seen else 0
            distance = sum(
                (float(a) - float(b)) ** 2
                for a, b in zip(volumes, best_volumes, strict=True)
            )
            return repeat_penalty, distance

        return sorted(candidate_volumes, key=score)

    @staticmethod
    def _convergence_signal(request: OptimizationRequest) -> float:
        values = [observation.objective_value for observation in request.observations]
        if len(values) < 3:
            return 0.0 if not values else 0.2
        recent = values[-5:]
        span = max(recent) - min(recent)
        denom = max(abs(min(recent)), 1e-9)
        relative_span = span / denom
        if relative_span < 0.01:
            return 0.8
        if relative_span < 0.05:
            return 0.6
        return 0.3
