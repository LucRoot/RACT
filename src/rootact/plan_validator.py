# Rooted by Dr. Lucas Root, Ph.D.

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from dataclasses import dataclass
from typing import Any

from rootact.core.plan import (
    SUPPORTED_SCHEMA_VERSIONS,
    dict_to_plan,
)
from rootact.manager import Plan


@dataclass
class ValidationResult:
    is_valid: bool
    message: str


@dataclass
class PlanValidator:
    """Validator for RootACT plans, including schema-version checks."""

    @staticmethod
    def validate(plan: Plan) -> ValidationResult:
        """Validate a runtime plan based on basic heuristics."""
        if not plan.assumption:
            return ValidationResult(False, "Plan assumption is empty.")
        if plan.confidence < 0.0 or plan.confidence > 1.0:
            return ValidationResult(False, f"Invalid confidence: {plan.confidence}")
        if not plan.steps:
            return ValidationResult(False, "Plan must contain at least one step.")
        for step in plan.steps:
            if not step.action:
                return ValidationResult(False, "Step action cannot be empty.")
            if not step.expected_artifact:
                return ValidationResult(
                    False, "Step expected_artifact cannot be empty."
                )
        return ValidationResult(True, "Plan is valid.")

    @staticmethod
    def validate_schema(data: dict[str, Any]) -> ValidationResult:
        """Validate a serialized plan against the supported schema versions."""
        version = data.get("schema_version")
        if version is None:
            return ValidationResult(
                False, "Missing schema_version; plan cannot be validated."
            )
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            return ValidationResult(
                False,
                f"Unknown schema version: {version}. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}.",
            )
        try:
            dict_to_plan(data)
        except (KeyError, ValueError, TypeError) as exc:
            return ValidationResult(False, f"Schema validation failed: {exc}")
        return ValidationResult(True, "Plan schema is valid.")


SUPPORTED_MIGRATION_HOPS: set[tuple[str, str]] = {
    ("0.9.0", "1.0.0"),
}


def migrate_plan(data: dict[str, Any], target_version: str) -> dict[str, Any] | None:
    """Migrate a serialized plan to target_version, or return None if unsupported.

    Only one-version hops are supported; older plans are marked frozen.
    """
    source_version = data.get("schema_version")
    if source_version == target_version:
        return dict(data)
    if (source_version, target_version) not in SUPPORTED_MIGRATION_HOPS:
        return None

    migrated = dict(data)
    migrated["schema_version"] = target_version

    # 0.9.0 -> 1.0.0: rename 'artifact' to 'expected_artifact' on each step.
    if source_version == "0.9.0" and target_version == "1.0.0":
        steps = migrated.get("steps", [])
        migrated["steps"] = []
        for step in steps:
            new_step = dict(step)
            if "artifact" in new_step and "expected_artifact" not in new_step:
                new_step["expected_artifact"] = new_step.pop("artifact")
            if "tier" not in new_step:
                new_step["tier"] = "T1"
            migrated["steps"].append(new_step)
        if "budget" not in migrated:
            migrated["budget"] = {
                "max_iterations": 10,
                "wall_time_seconds": 300.0,
                "step_timeout_seconds": 60.0,
            }

    try:
        dict_to_plan(migrated)
    except (KeyError, ValueError, TypeError):
        return None
    return migrated


# RACT 0.2.0
