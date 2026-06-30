from __future__ import annotations

import sys
from pathlib import Path

import pytest


WORKFLOW_ROOT = Path(__file__).resolve().parents[1]
if str(WORKFLOW_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKFLOW_ROOT))

from scripts.co_helios.co_helios_optimizer import CoHeliosOptimizer
from scripts.co_helios.optimization import (
    CandidateSuggestion,
    OptimizationDecisionPolicy,
    OptimizationObservation,
    OptimizationRequest,
    SearchDimension,
    volumes_to_params,
)


def dimensions(total_volume: float = 300.0) -> tuple[SearchDimension, ...]:
    return (
        SearchDimension("red", 0.0, total_volume),
        SearchDimension("green", 0.0, total_volume),
        SearchDimension("blue", 0.0, total_volume),
        SearchDimension("water", 0.0, total_volume),
    )


def request_with_history() -> OptimizationRequest:
    return OptimizationRequest(
        campaign_id="test-campaign",
        dimensions=dimensions(),
        observations=(
            OptimizationObservation(
                params=volumes_to_params([210.0, 30.0, 30.0, 30.0]),
                objective_value=18.0,
            ),
        ),
    )


def test_optimization_policy_rejects_duplicate_then_accepts_next_candidate():
    suggestion = CandidateSuggestion(
        candidates=(
            volumes_to_params([210.0, 30.0, 30.0, 30.0]),
            volumes_to_params([30.0, 210.0, 30.0, 30.0]),
        ),
        algorithm="space_filling",
        source="local_design_agent",
    )
    policy = OptimizationDecisionPolicy(total_volume=300.0)

    decision = policy.evaluate(suggestion, request_with_history())

    assert decision.accepted is True
    assert decision.final_candidates == (volumes_to_params([30.0, 210.0, 30.0, 30.0]),)
    assert "duplicate" in decision.rejection_reasons[0]
    assert any("accepted" in line for line in decision.decision_trace)


def test_optimization_policy_uses_safety_check_as_hard_gate():
    suggestion = CandidateSuggestion(
        candidates=(volumes_to_params([75.0, 75.0, 75.0, 75.0]),),
        algorithm="space_filling",
        source="local_design_agent",
    )
    request = OptimizationRequest(
        campaign_id="test-campaign",
        dimensions=dimensions(),
        observations=(),
    )

    policy = OptimizationDecisionPolicy(
        total_volume=300.0,
        safety_check=lambda _volumes: (False, ["synthetic veto"], 0.0),
    )

    decision = policy.evaluate(suggestion, request)

    assert decision.accepted is False
    assert decision.requires_human_review is True
    assert "synthetic veto" in decision.rejection_reasons[0]


def test_co_helios_suggestion_includes_optimization_layer_metadata():
    optimizer = CoHeliosOptimizer(
        target_colour=(180, 60, 40),
        total_volume=300.0,
        max_rounds=12,
        batch_size=4,
        seed=7,
    )

    optimizer.observe([210.0, 30.0, 30.0, 30.0], (190, 50, 40), 8.5)
    optimizer.observe([30.0, 210.0, 30.0, 30.0], (80, 180, 40), 35.0)
    optimizer.observe([30.0, 30.0, 210.0, 30.0], (70, 60, 190), 42.0)

    suggestion = optimizer.suggest()

    assert suggestion.optimizer == "CO_HELIOS"
    assert sum(suggestion.volumes) == pytest.approx(300.0)
    assert suggestion.metadata["agent_chain"] == [
        "PlannerAgent",
        "DesignAgent",
        "SafetyAgent",
    ]
    assert suggestion.metadata["integration_chain"] == [
        "PlannerAgent",
        "DesignAgent",
        "OptimizationAgent",
        "SafetyAgent",
    ]
    assert suggestion.metadata["optimization"]["decision"]["accepted"] is True
    assert suggestion.metadata["optimization_decisions"][0]["selected"] == "candidate_selected"
