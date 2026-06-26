"""Markdown/report helpers for CO-HELIOS suggestions."""

from __future__ import annotations

from typing import Any


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def co_helios_report_rows(suggestion: Any) -> list[tuple[str, str]]:
    """Return report table rows proving the CO-HELIOS chain was used."""

    metadata = getattr(suggestion, "metadata", {}) or {}
    plan = metadata.get("plan", {}) or {}
    optimization = metadata.get("optimization", {}) or {}
    safety = metadata.get("safety", {}) or {}
    trace = {
        "planner_decisions": metadata.get("planner_decisions", []),
        "design_decisions": metadata.get("design_decisions", []),
        "optimization_decisions": metadata.get("optimization_decisions", []),
        "safety_decisions": metadata.get("safety_decisions", []),
    }
    return [
        ("Optimizer", _fmt(getattr(suggestion, "optimizer", "CO_HELIOS"))),
        ("Planner phase", _fmt(plan.get("phase"))),
        ("Planner strategy", _fmt(plan.get("strategy"))),
        ("Planner resource estimate", _fmt(plan.get("resource_estimate"))),
        ("Candidate confidence", _fmt(metadata.get("candidate_confidence"))),
        ("Optimization strategy", _fmt(optimization.get("strategy_selected"))),
        ("Optimization convergence signal", _fmt(optimization.get("convergence_signal"))),
        ("Optimization decision trace", _fmt(optimization.get("decision_trace"))),
        ("Safety score", _fmt(safety.get("safety_score"))),
        ("Safety violations", _fmt(safety.get("violations"))),
        ("Agent decision trace", _fmt(trace)),
    ]


def co_helios_report_markdown_rows(suggestion: Any) -> str:
    """Format CO-HELIOS metadata rows for an iteration field table."""

    return "\n".join(f"| {key} | {value} |" for key, value in co_helios_report_rows(suggestion))
