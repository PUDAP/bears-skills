"""CO-HELIOS optimizer adapter for Bears colour-mixing experiments.

This module implements a local PUDA optimizer agent chain:

    PlannerAgent -> DesignAgent -> SafetyAgent -> validated optimizer result

The public optimizer API mirrors the existing Bears colour-mixing optimizers:
call ``observe(...)`` with completed runs, then ``suggest()`` to receive an
object with ``volumes`` in ``[R, G, B, water]`` order.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentDecision:
    """Audit record for one agent decision point."""

    id: str
    label: str
    options: list[str]
    selected: str
    reason: str
    outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "options": list(self.options),
            "selected": self.selected,
            "reason": self.reason,
            "outcome": self.outcome,
        }


@dataclass(frozen=True)
class CoHeliosSuggestionResult:
    """Validated RGBy suggestion returned by :class:`CoHeliosOptimizer`."""

    volumes: list[float]
    optimizer: str = "CO_HELIOS"
    llm_reasoning: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoundPlan:
    """Planner output for one optimizer step."""

    round_number: int
    phase: str
    strategy: str
    batch_size: int
    resource_estimate: dict[str, Any]
    notes: str
    decision_nodes: list[dict[str, Any]]


@dataclass(frozen=True)
class CandidateSafetyReport:
    """SafetyAgent decision for a candidate volume vector."""

    allowed: bool
    violations: list[str]
    safety_score: float
    requires_approval: bool = False
    decision_nodes: list[dict[str, Any]] = field(default_factory=list)
    granularity_used: str = "fine"


@dataclass(frozen=True)
class CandidateConfidence:
    """DesignAgent confidence note for one generated candidate."""

    candidate_index: int
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_index": self.candidate_index,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class PlannerAgent:
    """Round planner for colour-mixing optimization."""

    def __init__(self, *, max_rounds: int = 12, batch_size: int = 8) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.max_rounds = max_rounds
        self.batch_size = batch_size

    def plan(self, *, completed_rounds: int, n_observations: int) -> RoundPlan:
        """Choose an exploration/exploitation/refinement strategy."""

        round_number = completed_rounds + 1
        progress = round_number / max(self.max_rounds, 1)
        remaining_rounds = max(self.max_rounds - completed_rounds, 0)

        budget_decision = AgentDecision(
            id="budget_check",
            label="Budget check",
            options=["stop", "proceed"],
            selected="stop" if remaining_rounds <= 0 else "proceed",
            reason=f"max_rounds={self.max_rounds}, completed_rounds={completed_rounds}",
            outcome=f"{remaining_rounds} round(s) remaining",
        )

        if n_observations < 3 or progress <= 0.2:
            phase = "exploration"
            strategy = "space_filling"
            notes = "Use simplex-wide candidates because history is sparse."
        elif progress <= 0.8:
            phase = "exploitation"
            strategy = "best_guided"
            notes = "Sample around the best observed Delta E 2000 result."
        else:
            phase = "refinement"
            strategy = "local_refinement"
            notes = "Use small moves near the current best mix."

        strategy_decision = AgentDecision(
            id=f"round_{round_number}_strategy",
            label=f"Round {round_number} strategy",
            options=["space_filling", "best_guided", "local_refinement"],
            selected=strategy,
            reason=(
                f"phase={phase}, progress={progress:.2f}, "
                f"n_observations={n_observations}"
            ),
            outcome=notes,
        )

        return RoundPlan(
            round_number=round_number,
            phase=phase,
            strategy=strategy,
            batch_size=self.batch_size,
            resource_estimate={
                "tips_needed": self.batch_size * 4,
                "instruments": ["ot2", "camera"],
                "estimated_duration_minutes": self.batch_size * 5,
            },
            notes=notes,
            decision_nodes=[budget_decision.to_dict(), strategy_decision.to_dict()],
        )


class DesignAgent:
    """Generate candidate RGBy mixes from history and a round plan."""

    LOW_CONFIDENCE_THRESHOLD = 0.3

    def __init__(self, *, total_volume: float, seed: int | None = None) -> None:
        if total_volume <= 0:
            raise ValueError("total_volume must be positive")
        self.total_volume = float(total_volume)
        self._rng = random.Random(seed)
        self.last_confidence: list[CandidateConfidence] = []
        self.last_decision_nodes: list[dict[str, Any]] = []

    def propose(
        self,
        *,
        plan: RoundPlan,
        history: list[dict[str, Any]],
        target_colour: tuple[int, int, int] | None = None,
    ) -> list[list[float]]:
        """Return candidate ``[R, G, B, water]`` vectors."""

        if plan.strategy == "space_filling" or not history:
            candidates = self._space_filling_candidates(plan.batch_size)
            self._record_confidence(candidates, reason="space-filling exploration")
            return candidates

        best = min(history, key=lambda row: float(row["delta_e_2000"]))
        best_volumes = [float(v) for v in best["volumes"]]
        step_fraction = 0.18 if plan.strategy == "best_guided" else 0.08

        candidates = [
            self._colour_direction_candidate(best_volumes, best.get("rgb"), target_colour),
            best_volumes,
        ]
        while len(candidates) < plan.batch_size:
            candidates.append(self._jitter(best_volumes, step_fraction))
        self._record_confidence(candidates, reason=f"{plan.strategy} around best observation")
        return candidates

    def _record_confidence(self, candidates: list[list[float]], *, reason: str) -> None:
        """Store lightweight candidate confidence metadata for reporting."""

        confidence = 0.25 if "space-filling" in reason else 0.65
        self.last_confidence = [
            CandidateConfidence(i, confidence, reason)
            for i, _ in enumerate(candidates)
        ]
        selected = (
            "all_low_confidence"
            if confidence < self.LOW_CONFIDENCE_THRESHOLD
            else "usable_confidence"
        )
        self.last_decision_nodes = [
            AgentDecision(
                id="candidate_confidence",
                label="Candidate confidence",
                options=["all_low_confidence", "usable_confidence"],
                selected=selected,
                reason=reason,
                outcome=f"{len(candidates)} candidate(s) generated",
            ).to_dict()
        ]

    def _space_filling_candidates(self, n: int) -> list[list[float]]:
        anchors = [
            [0.70, 0.10, 0.10, 0.10],
            [0.10, 0.70, 0.10, 0.10],
            [0.10, 0.10, 0.70, 0.10],
            [0.20, 0.20, 0.20, 0.40],
            [0.40, 0.20, 0.20, 0.20],
            [0.20, 0.40, 0.20, 0.20],
            [0.20, 0.20, 0.40, 0.20],
            [0.25, 0.25, 0.25, 0.25],
        ]
        out = [self._scale_ratios(ratios) for ratios in anchors[:n]]
        while len(out) < n:
            draws = [self._rng.random() for _ in range(4)]
            out.append(self._scale_ratios(draws))
        return out

    def _colour_direction_candidate(
        self,
        best_volumes: list[float],
        mixed_rgb: tuple[int, int, int] | None,
        target_colour: tuple[int, int, int] | None,
    ) -> list[float]:
        if mixed_rgb is None or target_colour is None:
            return self._jitter(best_volumes, 0.12)

        candidate = list(best_volumes)
        step = self.total_volume * 0.08
        for idx, (mixed, target) in enumerate(zip(mixed_rgb, target_colour, strict=True)):
            delta = target - mixed
            if abs(delta) < 8:
                continue
            candidate[idx] += step if delta > 0 else -step
            candidate[3] -= step if delta > 0 else -step
        return self._project_to_simplex(candidate)

    def _jitter(self, center: list[float], step_fraction: float) -> list[float]:
        span = self.total_volume * step_fraction
        perturbed = [
            float(value) + self._rng.uniform(-span, span)
            for value in center
        ]
        return self._project_to_simplex(perturbed)

    def _scale_ratios(self, ratios: list[float]) -> list[float]:
        total = sum(float(v) for v in ratios)
        if total <= 0:
            raise ValueError("Candidate ratios must sum to a positive value")
        return [float(v) / total * self.total_volume for v in ratios]

    def _project_to_simplex(self, values: list[float]) -> list[float]:
        clipped = [max(0.0, float(v)) for v in values]
        total = sum(clipped)
        if total <= 0:
            return [self.total_volume / 4.0] * 4
        return [v / total * self.total_volume for v in clipped]


class SafetyAgent:
    """Safety gate for colour-mixing optimizer candidates."""

    MARGINAL_THRESHOLD = 0.8
    VETO_THRESHOLD = 0.5

    def __init__(
        self,
        *,
        total_volume: float,
        tolerance_ul: float = 1.0,
        max_component_fraction: float = 1.0,
    ) -> None:
        self.total_volume = float(total_volume)
        self.tolerance_ul = float(tolerance_ul)
        self.max_component_fraction = float(max_component_fraction)

    def check(self, volumes: list[float]) -> CandidateSafetyReport:
        """Validate a candidate before it can be returned to the workflow."""

        violations: list[str] = []
        if len(volumes) != 4:
            violations.append(f"Expected 4 volumes, got {len(volumes)}")
            return self._build_report(violations, n_checks=4)

        values: list[float] = []
        for value in volumes:
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                violations.append(f"Non-numeric volume: {value!r}")
                continue
            if not math.isfinite(numeric):
                violations.append(f"Non-finite volume: {value!r}")
            if numeric < 0:
                violations.append(f"Negative volume: {numeric:.3f}")
            values.append(numeric)

        total = sum(values)
        if abs(total - self.total_volume) > self.tolerance_ul:
            violations.append(
                f"Volumes sum to {total:.3f} uL, expected {self.total_volume:.3f} uL"
            )

        max_component = self.total_volume * self.max_component_fraction
        if any(v > max_component + self.tolerance_ul for v in values):
            violations.append(
                f"A component exceeds {self.max_component_fraction:.0%} of total volume"
            )

        return self._build_report(violations, n_checks=4)

    def _build_report(
        self,
        violations: list[str],
        *,
        n_checks: int,
    ) -> CandidateSafetyReport:
        safety_score = max(0.0, 1.0 - len(violations) / max(n_checks, 1))
        allowed = not violations and safety_score >= self.VETO_THRESHOLD
        requires_approval = allowed and safety_score < self.MARGINAL_THRESHOLD

        preflight = AgentDecision(
            id="preflight_check",
            label="Safety preflight check",
            options=["approved", "denied"],
            selected="approved" if allowed else "denied",
            reason=f"{len(violations)} violation(s) across {n_checks} check(s)",
            outcome="; ".join(violations) if violations else "No violations",
        )
        escalation = AgentDecision(
            id="escalation",
            label="Escalation required?",
            options=["auto_approved", "requires_review", "vetoed"],
            selected=(
                "vetoed"
                if not allowed
                else "requires_review"
                if requires_approval
                else "auto_approved"
            ),
            reason=(
                f"safety_score={safety_score:.2f}, "
                f"marginal_threshold={self.MARGINAL_THRESHOLD:.2f}, "
                f"veto_threshold={self.VETO_THRESHOLD:.2f}"
            ),
        )
        return CandidateSafetyReport(
            allowed=allowed,
            violations=violations,
            safety_score=safety_score,
            requires_approval=requires_approval,
            decision_nodes=[preflight.to_dict(), escalation.to_dict()],
            granularity_used="fine",
        )


class CoHeliosOptimizer:
    """Planner/Design/Safety optimizer for RGBy colour mixing.

    This optimizer is deterministic except for candidate jitter. It keeps the
    Bears workflow responsible for protocol generation, image processing,
    Delta E 2000 scoring, and reporting.
    """

    def __init__(
        self,
        *,
        target_colour: tuple[int, int, int] | None = None,
        total_volume: float = 300.0,
        max_rounds: int = 12,
        batch_size: int = 8,
        seed: int | None = None,
    ) -> None:
        self.target_colour = target_colour
        self.total_volume = float(total_volume)
        self.planner = PlannerAgent(max_rounds=max_rounds, batch_size=batch_size)
        self.design_agent = DesignAgent(total_volume=total_volume, seed=seed)
        self.safety_agent = SafetyAgent(total_volume=total_volume)
        self._history: list[dict[str, Any]] = []
        self.last_plan: RoundPlan | None = None
        self.last_safety_report: CandidateSafetyReport | None = None
        self.last_candidates: list[list[float]] = []

    def observe(
        self,
        volumes: list[float],
        mixed_rgb: tuple[int, int, int],
        delta_e_2000: float,
    ) -> None:
        """Record a completed colour-mixing observation."""

        normalized = self._normalize_volumes(volumes)
        report = self.safety_agent.check(normalized)
        if not report.allowed:
            raise ValueError(
                "Observed volumes failed safety validation: "
                + "; ".join(report.violations)
            )
        self._history.append(
            {
                "iteration": len(self._history) + 1,
                "volumes": normalized,
                "rgb": tuple(int(v) for v in mixed_rgb),
                "delta_e_2000": float(delta_e_2000),
            }
        )

    def suggest(self) -> CoHeliosSuggestionResult:
        """Return the next safety-approved RGBy candidate."""

        plan = self.planner.plan(
            completed_rounds=len(self._history),
            n_observations=len(self._history),
        )
        candidates = self.design_agent.propose(
            plan=plan,
            history=self._history,
            target_colour=self.target_colour,
        )
        self.last_plan = plan
        self.last_candidates = candidates

        ranked = self._rank_candidates(candidates)
        rejected: list[dict[str, Any]] = []
        for candidate in ranked:
            normalized = self._normalize_volumes(candidate)
            report = self.safety_agent.check(normalized)
            if report.allowed:
                self.last_safety_report = report
                return CoHeliosSuggestionResult(
                    volumes=normalized,
                    llm_reasoning=self._reasoning(plan, normalized, report),
                    metadata={
                        "plan": plan.__dict__,
                        "planner_decisions": plan.decision_nodes,
                        "design_decisions": self.design_agent.last_decision_nodes,
                        "candidate_confidence": [
                            item.to_dict()
                            for item in self.design_agent.last_confidence
                        ],
                        "safety": report.__dict__,
                        "safety_decisions": report.decision_nodes,
                        "rejected_candidates": rejected,
                    },
                )
            rejected.append({"volumes": candidate, "violations": report.violations})

        raise ValueError("SafetyAgent rejected every CO-HELIOS candidate.")

    @property
    def n_observations(self) -> int:
        return len(self._history)

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def _rank_candidates(self, candidates: list[list[float]]) -> list[list[float]]:
        if not self._history:
            return candidates
        best = min(self._history, key=lambda row: float(row["delta_e_2000"]))
        best_volumes = [float(v) for v in best["volumes"]]
        seen = {tuple(round(float(v), 6) for v in row["volumes"]) for row in self._history}

        def score(candidate: list[float]) -> tuple[int, float]:
            key = tuple(round(float(v), 6) for v in candidate)
            repeat_penalty = 1 if key in seen else 0
            distance = sum((float(a) - float(b)) ** 2 for a, b in zip(candidate, best_volumes, strict=True))
            return repeat_penalty, distance

        return sorted(candidates, key=score)

    def _normalize_volumes(self, volumes: list[float]) -> list[float]:
        if len(volumes) == 3:
            volumes = [*volumes, self.total_volume - sum(float(v) for v in volumes)]
        if len(volumes) != 4:
            raise ValueError(f"Expected 4 volumes [R,G,B,water], got {len(volumes)}")
        values = [float(v) for v in volumes]
        if any(not math.isfinite(v) for v in values):
            raise ValueError(f"Volumes must be finite: {volumes}")
        if any(v < 0 for v in values):
            raise ValueError(f"Volumes must be non-negative: {volumes}")
        total = sum(values)
        if total <= 0:
            raise ValueError("Volume sum must be positive")
        return [v / total * self.total_volume for v in values]

    def _reasoning(
        self,
        plan: RoundPlan,
        volumes: list[float],
        report: CandidateSafetyReport,
    ) -> str:
        r, g, b, w = volumes
        if self._history:
            best = min(self._history, key=lambda row: float(row["delta_e_2000"]))
            best_note = f" best observed Delta E 2000 is {best['delta_e_2000']:.4f}."
        else:
            best_note = " no completed observations are available yet."
        return (
            f"CO-HELIOS selected {plan.strategy} during {plan.phase};"
            f"{best_note} SafetyAgent approved the candidate with score "
            f"{report.safety_score:.2f}. Suggested volumes are "
            f"R={r:.2f}, G={g:.2f}, B={b:.2f}, water={w:.2f} uL."
        )


HELIOSOptimizer = CoHeliosOptimizer
