"""Versioned plan schema types for RACT."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from ract.canonical import dumps_jcs


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


@dataclass(frozen=True)
class PlanDiff:
    """Difference between two plans, keyed by ``step_id``.

    ``added_step_ids`` and ``removed_step_ids`` name steps present in
    exactly one of the two plans. ``modified_step_ids`` names steps
    present in both whose content_digest differs — a rewording, tier
    change, tool_call swap, or parent-list edit all count as "modified".

    The three sets are pairwise disjoint. Ordering does not participate:
    two plans with the same step ids in different positions produce an
    empty diff, matching the intended "did the plan mutate?" question
    (loop reorderings are noise, additions and content changes are the
    signal).
    """

    added_step_ids: tuple[str, ...] = ()
    removed_step_ids: tuple[str, ...] = ()
    modified_step_ids: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.added_step_ids or self.removed_step_ids or self.modified_step_ids
        )

    def to_payload(self) -> dict[str, Any]:
        """Return a canonical JSON-serialisable dict for the event payload."""
        return {
            "added_step_ids": list(self.added_step_ids),
            "removed_step_ids": list(self.removed_step_ids),
            "modified_step_ids": list(self.modified_step_ids),
        }


def step_content_digest(step: StepSchema) -> str:
    """Return a stable SHA-256 hex digest of a step's semantic content.

    Deliberately excludes ``step_id`` — otherwise every rebuilt plan
    would appear "modified". Includes every other field so a rewording,
    tier change, tool_call swap, or dependency-list edit surfaces as a
    modification.
    """
    payload = {
        "action": step.action,
        "provider_hint": step.provider_hint,
        "expected_artifact": step.expected_artifact,
        "tier": step.tier,
        "assumption_ids": list(step.assumption_ids),
        "parent_step_ids": list(step.parent_step_ids),
        "tool_call": step.tool_call,
    }
    # v0.5.1 module_03: RFC 8785 JCS canonical bytes.
    return hashlib.sha256(dumps_jcs(payload)).hexdigest()


def diff_plans(old: PlanSchema, new: PlanSchema) -> PlanDiff:
    """Return the :class:`PlanDiff` between ``old`` and ``new``.

    Two plans are compared by their ``steps`` collection; milestones,
    budget, and assumption text do not participate. Same-id steps whose
    content_digest changes are recorded in ``modified_step_ids``. The
    result's three lists are individually sorted so replay is stable.
    """
    old_by_id = {s.step_id: s for s in old.steps}
    new_by_id = {s.step_id: s for s in new.steps}
    old_ids = set(old_by_id)
    new_ids = set(new_by_id)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    modified: list[str] = []
    for step_id in sorted(new_ids & old_ids):
        if step_content_digest(old_by_id[step_id]) != step_content_digest(
            new_by_id[step_id]
        ):
            modified.append(step_id)
    return PlanDiff(
        added_step_ids=tuple(added),
        removed_step_ids=tuple(removed),
        modified_step_ids=tuple(modified),
    )


def diff_manager_plans(old: Any, new: Any) -> PlanDiff:
    """Diff two ``ract.manager.Plan`` values by step content (order-insensitive).

    The manager's ``Plan`` type predates ``PlanSchema`` and does not
    carry ``step_id`` per step. Content-hash stands in for identity so
    a re-plan that reorders identical steps produces an empty diff and
    a genuine content mutation surfaces as removed + added (the
    manager plan has no persistent step identity to preserve, so
    "modified" collapses into that pair).

    Duplicate-content steps disambiguate by occurrence index so a plan
    dropping one of two identical steps still surfaces the removal.

    Cluster 2 second-pass fix — was position-keyed; reordered identical
    plans generated false-positive plan.rewritten events.
    """

    def _content_keyed_steps(plan: Any) -> list[StepSchema]:
        steps = getattr(plan, "steps", ()) or ()
        seen_counts: dict[str, int] = {}
        keyed: list[StepSchema] = []
        for s in steps:
            temp = StepSchema(
                step_id="",
                action=str(getattr(s, "action", "")),
                provider_hint=str(getattr(s, "provider_hint", "")),
                expected_artifact=str(getattr(s, "expected_artifact", "")),
                tool_call=getattr(s, "tool_call", None),
            )
            digest = step_content_digest(temp)
            occurrence = seen_counts.get(digest, 0)
            seen_counts[digest] = occurrence + 1
            keyed.append(
                StepSchema(
                    step_id=f"{digest}-{occurrence}",
                    action=temp.action,
                    provider_hint=temp.provider_hint,
                    expected_artifact=temp.expected_artifact,
                    tool_call=temp.tool_call,
                )
            )
        return keyed

    dummy_old = PlanSchema(
        schema_version=CURRENT_SCHEMA_VERSION,
        assumption="",
        confidence=1.0,
        steps=_content_keyed_steps(old),
    )
    dummy_new = PlanSchema(
        schema_version=CURRENT_SCHEMA_VERSION,
        assumption="",
        confidence=1.0,
        steps=_content_keyed_steps(new),
    )
    return diff_plans(dummy_old, dummy_new)


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
