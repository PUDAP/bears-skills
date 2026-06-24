"""Small HELIOS-compatible agent primitives for local PUDA workflows.

The upstream HELIOS agents share a common BaseAgent shape and emit
DecisionNode records for auditability.  This local version keeps that contract
without requiring the full HELIOS application stack inside Bears workflows.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass(frozen=True)
class DecisionNode:
    """One auditable agent decision."""

    id: str
    label: str
    options: list[str]
    selected: str
    reason: str
    outcome: str = ""
    children: tuple["DecisionNode", ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "options": list(self.options),
            "selected": self.selected,
            "reason": self.reason,
            "outcome": self.outcome,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class AgentResult(Generic[OutputT]):
    """Result wrapper matching the HELIOS agent runtime shape."""

    success: bool
    output: OutputT | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    agent_name: str = ""
    trace_id: str = ""
    decision_tree: list[dict[str, Any]] = field(default_factory=list)


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Minimal synchronous BaseAgent for optimizer-only PUDA integration."""

    name = "base_agent"
    description = ""
    layer = "L0"

    def validate_input(self, input_data: InputT) -> list[str]:
        return []

    @abstractmethod
    def process(self, input_data: InputT) -> OutputT:
        """Execute the agent-specific step."""

    def run(self, input_data: InputT, trace_id: str | None = None) -> AgentResult[OutputT]:
        if trace_id is None:
            trace_id = uuid.uuid4().hex[:12]
        start = time.monotonic()
        errors = self.validate_input(input_data)
        if errors:
            return AgentResult(
                success=False,
                errors=errors,
                agent_name=self.name,
                trace_id=trace_id,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        try:
            output = self.process(input_data)
        except Exception as exc:
            return AgentResult(
                success=False,
                errors=[str(exc)],
                agent_name=self.name,
                trace_id=trace_id,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        decision_tree = getattr(output, "decision_nodes", [])
        return AgentResult(
            success=True,
            output=output,
            agent_name=self.name,
            trace_id=trace_id,
            duration_ms=(time.monotonic() - start) * 1000,
            decision_tree=list(decision_tree),
        )
