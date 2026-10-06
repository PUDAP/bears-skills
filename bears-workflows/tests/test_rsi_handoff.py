import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "RSI optimization" / "rsi_handoff.py"
SPEC = importlib.util.spec_from_file_location("rsi_handoff", MODULE_PATH)
rsi_handoff = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(rsi_handoff)


def _request():
    return rsi_handoff.build_evaluation_request(
        run_id="run-1",
        iteration=2,
        volumes=[80, 70, 60, 90],
        measured_rgb=[170, 80, 55],
        target_rgb=[180, 60, 40],
        total_volume_ul=300,
    )


def test_valid_evaluator_handoff_is_normalized():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["evaluation"] = "Red is low; increase red while preserving total volume."
    handoff["suggestion"] = {
        "red_ul": 90,
        "green_ul": 65,
        "blue_ul": 55,
        "water_ul": 90,
    }

    result = rsi_handoff.validate_evaluator_handoff(
        handoff,
        expected_observation_sha256=request["observation_sha256"],
        total_volume_ul=300,
        expected_next_iteration=3,
    )

    assert result["suggestion"]["red_ul"] == 90.0
    assert sum(result["suggestion"].values()) == 300.0
    assert result["executable"] is True


def test_evaluator_can_define_an_observation_only_method():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["evaluation_method"] = {
        "name": "rgb_mae",
        "source": "evaluator_defined",
        "goal": "minimize",
        "value": 15.0,
        "definition": "Mean absolute error across RGB channels.",
        "calculation": "(|170-180| + |80-60| + |55-40|) / 3",
        "uses_only_observation_data": True,
    }
    handoff["evaluation"] = "MAE makes the channel deviations directly interpretable."
    handoff["suggestion"] = {
        "red_ul": 90,
        "green_ul": 65,
        "blue_ul": 55,
        "water_ul": 90,
    }

    result = rsi_handoff.validate_evaluator_handoff(
        handoff,
        expected_observation_sha256=request["observation_sha256"],
        total_volume_ul=300,
        expected_next_iteration=3,
    )

    assert result["evaluation_method"]["name"] == "rgb_mae"
    assert result["evaluation_method"]["source"] == "evaluator_defined"


def test_workflow_change_is_a_non_executable_proposal():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["decision"] = "propose_workflow_change"
    handoff["evaluation"] = "Repeated channel imbalance suggests revising image sampling."
    handoff["suggestion"] = None
    handoff["workflow_change"] = {
        "action": "propose",
        "proposal": "Capture three images and use the median RGB per channel.",
        "rationale": "Reduce sensitivity to transient lighting noise.",
        "requires_user_approval": True,
    }

    result = rsi_handoff.validate_evaluator_handoff(
        handoff,
        expected_observation_sha256=request["observation_sha256"],
        total_volume_ul=300,
        expected_next_iteration=3,
    )

    assert result["decision"] == "propose_workflow_change"
    assert result["executable"] is False


def test_named_precomputed_metric_is_rejected():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["evaluation_method"] = "precomputed_metric"
    handoff["evaluation"] = "This must not bypass the evaluator declaration."

    with pytest.raises(rsi_handoff.HandoffValidationError, match="evaluator-defined object"):
        rsi_handoff.validate_evaluator_handoff(
            handoff,
            expected_observation_sha256=request["observation_sha256"],
            total_volume_ul=300,
            expected_next_iteration=3,
        )


def test_stale_observation_is_rejected():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["observation_sha256"] = "stale"
    handoff["evaluation"] = "Try another point."
    handoff["suggestion"] = {
        "red_ul": 75,
        "green_ul": 75,
        "blue_ul": 75,
        "water_ul": 75,
    }

    with pytest.raises(rsi_handoff.HandoffValidationError, match="latest observation"):
        rsi_handoff.validate_evaluator_handoff(
            handoff,
            expected_observation_sha256=request["observation_sha256"],
            total_volume_ul=300,
            expected_next_iteration=3,
        )


def test_invalid_volume_sum_is_rejected():
    request = _request()
    handoff = rsi_handoff.evaluator_handoff_template(request)
    handoff["evaluation"] = "Try another point."
    handoff["suggestion"] = {
        "red_ul": 100,
        "green_ul": 100,
        "blue_ul": 100,
        "water_ul": 100,
    }

    with pytest.raises(rsi_handoff.HandoffValidationError, match="must sum"):
        rsi_handoff.validate_evaluator_handoff(
            handoff,
            expected_observation_sha256=request["observation_sha256"],
            total_volume_ul=300,
            expected_next_iteration=3,
        )
