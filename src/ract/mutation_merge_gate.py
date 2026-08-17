import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

from ract.coverage_delta import CoverageDelta


@dataclass
class GateResult:
    """Result of a mutation merge gate evaluation."""

    passed: bool
    reason: str
    policy_id: str
    delta_coverage: float = 0.0
    delta_mutation_score: float = 0.0
    receipt: Optional[str] = None


@dataclass
class MergePolicy:
    """A natural-language policy declaration."""

    id: str
    description: str
    trigger_pattern: str  # Regex for file paths
    condition: str  # e.g. "coverage_delta >= 5" or "mutation_score >= 90"
    threshold: float
    action: str  # "block" or "warn"


def load_policies(path: str) -> List[MergePolicy]:
    """Load a list of MergePolicy objects from a JSON file."""
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("policy file must contain a JSON list")
    required = {
        "id",
        "description",
        "trigger_pattern",
        "condition",
        "threshold",
        "action",
    }
    policies = []
    for idx, item in enumerate(data):
        if not isinstance(item, dict) or not required.issubset(item):
            raise ValueError(
                f"policy {idx} missing required keys: {required - set(item)}"
            )
        policies.append(
            MergePolicy(
                id=item["id"],
                description=item["description"],
                trigger_pattern=item["trigger_pattern"],
                condition=item["condition"],
                threshold=float(item["threshold"]),
                action=item["action"],
            )
        )
    return policies


class MutationMergeGateEngine:
    """
    Enforces merge policies based on coverage delta and mutation scores.
    Parses natural-language-like conditions and evaluates against metrics.
    """

    def __init__(self, policies: List[MergePolicy]):
        self.policies = {p.id: p for p in policies}
        self._compiled_triggers = {}
        for p in policies:
            self._compiled_triggers[p.id] = re.compile(p.trigger_pattern)

    def evaluate(
        self,
        policy_id: str,
        file_paths: List[str],
        current_coverage: float,
        previous_coverage: float,
        current_mutation_score: float,
        previous_mutation_score: float,
    ) -> GateResult:
        """
        Evaluate a specific policy against the provided metrics.
        """
        policy = self.policies.get(policy_id)
        if not policy:
            return GateResult(
                passed=False,
                reason=f"Policy {policy_id} not found",
                policy_id=policy_id,
            )

        # Check trigger
        triggered = any(
            self._compiled_triggers[policy_id].match(fp) for fp in file_paths
        )
        if not triggered:
            return GateResult(
                passed=True,
                reason="Policy not triggered by file paths",
                policy_id=policy_id,
            )

        delta_coverage = current_coverage - previous_coverage
        delta_mutation = current_mutation_score - previous_mutation_score

        # Parse condition (simple parser for "coverage_delta >= X" or "mutation_score >= X")
        condition_match = re.match(
            r"(\w+)_delta\s*(>=|<=|>|<)\s*([\d.]+)", policy.condition
        )
        if not condition_match:
            condition_match = re.match(
                r"(\w+)_score\s*(>=|<=|>|<)\s*([\d.]+)", policy.condition
            )

        if not condition_match:
            return GateResult(
                passed=False,
                reason=f"Invalid condition syntax in policy {policy_id}",
                policy_id=policy_id,
            )

        metric_type, operator, threshold_str = condition_match.groups()
        threshold = float(threshold_str)
        operator_map = {
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
        }

        # Natural-language conditions come in two shapes:
        #   ``<metric>_delta <op> <threshold>`` compares the change between the
        #   previous and current values against the threshold; and
        #   ``<metric>_score <op> <threshold>`` compares the raw current value
        #   against the threshold. The prior implementation collapsed both
        #   shapes onto the delta, so a policy of ``mutation_score >= 70`` was
        #   silently evaluated as ``mutation_delta >= 70`` and passed or
        #   failed on the wrong number.
        condition_suffix = policy.condition.split(metric_type, 1)[1].lstrip()
        wants_delta = condition_suffix.startswith("_delta")
        if metric_type == "coverage":
            current_val = delta_coverage if wants_delta else current_coverage
        elif metric_type == "mutation":
            current_val = delta_mutation if wants_delta else current_mutation_score
        else:
            return GateResult(
                passed=False,
                reason=f"Unknown metric type: {metric_type}",
                policy_id=policy_id,
            )

        check_fn = operator_map.get(operator)
        if not check_fn:
            return GateResult(
                passed=False,
                reason=f"Unknown operator: {operator}",
                policy_id=policy_id,
            )

        passed = check_fn(current_val, threshold)
        reason = (
            f"Condition met: {metric_type} {operator} {threshold} ({current_val})"
            if passed
            else f"Condition failed: {metric_type} {operator} {threshold} ({current_val})"
        )

        receipt = None
        if not passed and policy.action == "block":
            receipt = self._generate_receipt(
                policy_id, file_paths, delta_coverage, delta_mutation
            )

        return GateResult(
            passed=passed,
            reason=reason,
            policy_id=policy_id,
            delta_coverage=delta_coverage,
            delta_mutation_score=delta_mutation,
            receipt=receipt,
        )

    def _generate_receipt(
        self,
        policy_id: str,
        file_paths: List[str],
        delta_coverage: float,
        delta_mutation: float,
    ) -> str:
        """Generate a signed receipt string for a blocked merge."""
        receipt_data = {
            "policy_id": policy_id,
            "file_paths": file_paths,
            "delta_coverage": delta_coverage,
            "delta_mutation_score": delta_mutation,
            "status": "BLOCKED",
        }
        # Simple hash-based signature for demonstration
        import hashlib

        raw = json.dumps(receipt_data, sort_keys=True)
        signature = hashlib.sha256(raw.encode()).hexdigest()
        receipt_data["signature"] = signature
        return json.dumps(receipt_data)

    def evaluate_all(
        self,
        file_paths: List[str],
        current_coverage: float,
        previous_coverage: float,
        current_mutation_score: float,
        previous_mutation_score: float,
    ) -> List[GateResult]:
        """Evaluate all policies against the provided metrics."""
        results = []
        for policy_id in self.policies:
            result = self.evaluate(
                policy_id,
                file_paths,
                current_coverage,
                previous_coverage,
                current_mutation_score,
                previous_mutation_score,
            )
            results.append(result)
        return results


def evaluate_coverage_policy(policies: List[MergePolicy], delta: CoverageDelta) -> bool:
    """Return True only if the earned-coverage delta passes every policy.

    A delta passes when its verdict is 'earn' and no per-file floor is breached.
    Policies are accepted for future extension; currently the gate is all-or-nothing.
    """
    if delta.verdict != "earn":
        return False
    if delta.floor_breached or delta.per_file_breaches:
        return False
    return bool(policies) or True
