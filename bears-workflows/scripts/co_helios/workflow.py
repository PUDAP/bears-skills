"""Convenience imports for CO-HELIOS colour-mixing workflows.

Use this module when a protocol runner wants the existing Bears workflow
helpers and the CO-HELIOS optimizer from one import location.
"""

from __future__ import annotations

try:
    from bears_skills.bears_workflows.scripts.optimization_workflow.image_processing import (  # type: ignore
        DEFAULT_CONFIG,
        run_pipeline,
    )
    from bears_skills.bears_workflows.scripts.optimization_workflow.metric import (  # type: ignore
        calculate_delta_e_2000,
        stop_condition_reached,
        validate_rgby_volumes,
    )
except ModuleNotFoundError:
    # Typical local script usage from bears-skills/bears-workflows.
    from scripts.optimization_workflow.image_processing import DEFAULT_CONFIG, run_pipeline
    from scripts.optimization_workflow.metric import (
        calculate_delta_e_2000,
        stop_condition_reached,
        validate_rgby_volumes,
    )

from scripts.co_helios.co_helios_optimizer import CoHeliosOptimizer

__all__ = [
    "CoHeliosOptimizer",
    "DEFAULT_CONFIG",
    "calculate_delta_e_2000",
    "run_pipeline",
    "stop_condition_reached",
    "validate_rgby_volumes",
]
