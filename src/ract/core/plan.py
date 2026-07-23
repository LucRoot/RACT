"""Versioned plan schema types for RACT."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


CURRENT_SCHEMA_VERSION: str = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS: set[str] = {"1.0.0", "0.9.0"}


@dataclass(frozen=True)
class StepSchema:
    """One step in a versioned plan."""

    step_id: str
    action: str
    provider_hint: str = ""
    expected_artifact: str = ""
    tier: str = "T1"
    assumption_ids: tuple[str, ...] = ()
    parent_step_ids: tuple[str, ...] = ()
    tool_call: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.tier not in {"T0", "T1", "T2", "T3"}:
            raise ValueError(f"Invalid tier: {self.tier}")


@dataclass(frozen=True)
class MilestoneSchema:
    """One milestone in a versioned plan."""

    id: str
    description: str
    acceptance: str
    verifier_kind: str = "heuristic"
    verifier_config: dict[str, Any] = field(default_factory=dict)
    status: str = "open"

    def __post_init__(self) -> None:
        if self.status not in {"open", "done", "blocked"}:
            raise ValueError(f"Invalid milestone status: {self.status}")
        if self.verifier_kind not in {
            "heuristic",
            "test",
            "assertion",
            "artifact",
            "provider",
        }:
            raise ValueError(f"Invalid verifier_kind: {self.verifier_kind}")


@dataclass(frozen=True)
class BudgetSchema:
    """Budget constraints for a versioned plan."""

    max_iterations: int = 10
    wall_time_seconds: float = 300.0
    step_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")


@dataclass(frozen=True)
class PlanSchema:
    """Versioned plan schema."""

    schema_version: str
    assumption: str
    confidence: float
    steps: list[StepSchema]
    milestones: list[MilestoneSchema] = field(default_factory=list)
    budget: BudgetSchema = field(default_factory=BudgetSchema)
    assumption_registry: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(f"Unsupported schema version: {self.schema_version}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"Confidence out of range: {self.confidence}")


def plan_to_dict(plan: PlanSchema) -> dict[str, Any]:
    """Serialize a PlanSchema to a plain dictionary."""
    return {
        "schema_version": plan.schema_version,
        "assumption": plan.assumption,
        "confidence": plan.confidence,
        "steps": [
            {
                "step_id": s.step_id,
                "action": s.action,
                "provider_hint": s.provider_hint,
                "expected_artifact": s.expected_artifact,
                "tier": s.tier,
                "assumption_ids": list(s.assumption_ids),
                "parent_step_ids": list(s.parent_step_ids),
                "tool_call": s.tool_call,
            }
            for s in plan.steps
        ],
        "milestones": [
            {
                "id": m.id,
                "description": m.description,
                "acceptance": m.acceptance,
                "verifier_kind": m.verifier_kind,
                "verifier_config": m.verifier_config,
                "status": m.status,
            }
            for m in plan.milestones
        ],
        "budget": {
            "max_iterations": plan.budget.max_iterations,
            "wall_time_seconds": plan.budget.wall_time_seconds,
            "step_timeout_seconds": plan.budget.step_timeout_seconds,
        },
    }


def dict_to_plan(data: dict[str, Any]) -> PlanSchema:
    """Deserialize a plain dictionary to a PlanSchema."""
    steps = [
        StepSchema(
            step_id=s["step_id"],
            action=s["action"],
            provider_hint=s.get("provider_hint", ""),
            expected_artifact=s.get("expected_artifact", ""),
            tier=s.get("tier", "T1"),
            assumption_ids=tuple(s.get("assumption_ids", [])),
            parent_step_ids=tuple(s.get("parent_step_ids", [])),
            tool_call=s.get("tool_call"),
        )
        for s in data.get("steps", [])
    ]
    milestones = [
        MilestoneSchema(
            id=m["id"],
            description=m["description"],
            acceptance=m["acceptance"],
            verifier_kind=m.get("verifier_kind", "heuristic"),
            verifier_config=m.get("verifier_config", {}),
            status=m.get("status", "open"),
        )
        for m in data.get("milestones", [])
    ]
    budget_data = data.get("budget", {})
    budget = BudgetSchema(
        max_iterations=budget_data.get("max_iterations", 10),
        wall_time_seconds=budget_data.get("wall_time_seconds", 300.0),
        step_timeout_seconds=budget_data.get("step_timeout_seconds", 60.0),
    )
    return PlanSchema(
        schema_version=data["schema_version"],
        assumption=data["assumption"],
        confidence=data["confidence"],
        steps=steps,
        milestones=milestones,
        budget=budget,
    )


# RACT 0.2.0
