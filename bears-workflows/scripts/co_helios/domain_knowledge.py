"""Domain knowledge for CO-HELIOS colour-mixing optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ColourMixingDomainKnowledge:
    """Rules and report labels shared by the CO-HELIOS agents."""

    total_volume: float = 300.0
    tolerance_ul: float = 1.0
    max_component_fraction: float = 1.0

    @property
    def domain_name(self) -> str:
        return "colour_mixing"

    @property
    def dimensions(self) -> list[dict[str, Any]]:
        return [
            {
                "param_name": "red",
                "param_type": "number",
                "min_value": 0.0,
                "max_value": self.total_volume,
                "primitive": "robot.aspirate_dispense",
            },
            {
                "param_name": "green",
                "param_type": "number",
                "min_value": 0.0,
                "max_value": self.total_volume,
                "primitive": "robot.aspirate_dispense",
            },
            {
                "param_name": "blue",
                "param_type": "number",
                "min_value": 0.0,
                "max_value": self.total_volume,
                "primitive": "robot.aspirate_dispense",
            },
            {
                "param_name": "water",
                "param_type": "number",
                "min_value": 0.0,
                "max_value": self.total_volume,
                "primitive": "robot.aspirate_dispense",
            },
        ]

    def planner_strategy(self, *, completed_rounds: int, n_observations: int, max_rounds: int) -> tuple[str, str, str]:
        round_number = completed_rounds + 1
        progress = round_number / max(max_rounds, 1)
        if n_observations < 3 or progress <= 0.2:
            return "exploration", "space_filling", "Use simplex-wide candidates because history is sparse."
        if progress <= 0.8:
            return "exploitation", "best_guided", "Sample around the best observed Delta E 2000 result."
        return "refinement", "local_refinement", "Use small moves near the current best mix."

    def resource_estimate(self, *, batch_size: int) -> dict[str, Any]:
        return {
            "tips_needed": batch_size * 4,
            "instruments": ["ot2", "camera"],
            "estimated_duration_minutes": batch_size * 5,
        }

    def safety_policy(self) -> dict[str, Any]:
        return {
            "required_components": ["red", "green", "blue", "water"],
            "total_volume_ul": self.total_volume,
            "tolerance_ul": self.tolerance_ul,
            "max_component_fraction": self.max_component_fraction,
            "fine_grained_candidate_checks": True,
        }
