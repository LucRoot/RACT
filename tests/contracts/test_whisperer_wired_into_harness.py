"""module_08: WhispererContract is called from the shipped Harness planner path.

The DialectBrief must be injected into the planner prompt before
``self.planner.plan()`` runs. The model never sees the pre-injection
form — the environment enforces the injection.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ract.rooted import Rooted


def test_planner_prompt_carries_dialect_brief_when_harness_runs(tmp_path) -> None:
    """Harness.run injects the DialectBrief prefix before planner.plan()."""
    from ract.harness import Harness
    from ract.manager import Plan

    # Construct a fake planner whose plan() records the prompt it was
    # handed. We patch Harness.__init__ to skip provider/config wiring
    # and only exercise the injection code path in Harness.run.
    harness = object.__new__(Harness)
    harness.project_dir = tmp_path
    harness.config = {}
    harness.retrieval_adapter = None
    harness.legacy_whisperer = None
    harness.skills_registry = MagicMock()
    harness.skills_registry.invoke = MagicMock(side_effect=Exception("no skill"))
    harness.executor = MagicMock()
    harness.executor.execute = MagicMock(
        return_value=Rooted(
            value=None,
            assumption="planner failure precludes execution",
            confidence=0.0,
            provenance=[],
            error="unused",
        )
    )
    harness.planner = MagicMock()
    captured: dict[str, str] = {}

    def _capture_plan(prompt: str) -> Rooted[Plan]:
        captured["prompt"] = prompt
        return Rooted(
            value=None,
            assumption="planner fake refuses",
            confidence=0.0,
            provenance=[],
            error="stop-here",
        )

    harness.planner.plan = _capture_plan
    harness.coverage_gate_enabled = False
    harness.mutation_gate_enabled = False
    harness.git_mode = None

    with patch("ract.harness._curate_context", return_value=""):
        harness.run("write a hello world")

    assert "prompt" in captured, "planner.plan was never called"
    assert "## Codebase dialect brief" in captured["prompt"], (
        "WhispererContract did not inject the DialectBrief prefix; "
        "planner prompt is not environment-enforced."
    )


# RACT 0.4.0
