from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ract.manager import Plan
from ract.plan_serializers import plan_from_dict, plan_to_dict

_ROOT_KNOT = object()


@dataclass
class ReplayResult:
    """Outcome of replaying one plan step."""

    step_index: int
    action: str
    success: bool
    output: Any = None
    error: str = ""


@dataclass
class ReplayReport:
    """Outcome of replaying an entire plan."""

    plan: Plan
    results: list[ReplayResult] = field(default_factory=list)
    success: bool = False
    summary: str = ""


class PlanReplay:
    """
    Save, load, and replay RACT plans deterministically.

    PlanReplay does not execute real side effects. Instead it accepts an
    ``executor`` callable that receives a step's action string and returns the
    step's output. This keeps the module testable and safe while still verifying
    that a saved plan can be reconstructed and driven to the same outcomes.
    """

    _ROOT_KNOT = _ROOT_KNOT

    def save(self, plan: Plan, path: Path | str) -> None:
        """Serialize ``plan`` to ``path`` as JSON."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(plan_to_dict(plan), indent=2), encoding="utf-8")

    def load(self, path: Path | str) -> Plan:
        """Deserialize a plan from ``path``."""
        target = Path(path)
        data = json.loads(target.read_text(encoding="utf-8"))
        return plan_from_dict(data)

    def replay(
        self,
        plan: Plan,
        executor: Callable[[str], Any],
    ) -> ReplayReport:
        """
        Replay every step in ``plan`` through ``executor``.

        The executor receives the step's ``action`` string and returns an
        arbitrary output. If the executor raises an exception, the step is
        marked failed and replay continues so the full report is available.
        """
        results: list[ReplayResult] = []
        all_success = True
        for index, step in enumerate(plan.steps):
            try:
                output = executor(step.action)
                results.append(
                    ReplayResult(
                        step_index=index,
                        action=step.action,
                        success=True,
                        output=output,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                all_success = False
                results.append(
                    ReplayResult(
                        step_index=index,
                        action=step.action,
                        success=False,
                        error=str(exc),
                    )
                )
        report = ReplayReport(
            plan=plan,
            results=results,
            success=all_success,
        )
        report.summary = self._summarize(report)
        return report

    def verify_determinism(
        self,
        plan: Plan,
        executor: Callable[[str], Any],
        trials: int = 2,
    ) -> tuple[bool, list[ReplayReport]]:
        """
        Replay ``plan`` multiple times and confirm identical outcomes.

        Returns ``(deterministic, reports)``. Determinism requires every trial to
        succeed and every trial's serialized results to be equal.
        """
        reports = [self.replay(plan, executor) for _ in range(max(1, trials))]
        if not all(r.success for r in reports):
            return False, reports
        canonical = json.dumps(
            [self._result_key(r) for r in reports[0].results], sort_keys=True
        )
        deterministic = all(
            json.dumps([self._result_key(r) for r in report.results], sort_keys=True)
            == canonical
            for report in reports
        )
        return deterministic, reports

    @staticmethod
    def _result_key(result: ReplayResult) -> dict[str, Any]:
        """Return a JSON-serializable key for comparing step outcomes."""
        return {
            "step_index": result.step_index,
            "action": result.action,
            "success": result.success,
            "output": result.output,
            "error": result.error,
        }

    @staticmethod
    def _summarize(report: ReplayReport) -> str:
        total = len(report.results)
        passed = sum(1 for r in report.results if r.success)
        if report.success:
            return f"Replay succeeded: {passed}/{total} steps passed."
        return f"Replay failed: {passed}/{total} steps passed."


# RACT 0.1.1 - Trust and tooling
