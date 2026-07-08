# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RootAct LoopController."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rootact.executor import ExecutionReport, StepResult
from rootact.loop_controller import LoopController, LoopIteration
from rootact.loop_planner import Milestone
from rootact.manager import Plan, Step
from rootact.rooted import Rooted


def _make_report(
    artifacts: dict[str, str], project_dir: Path | None = None
) -> ExecutionReport:
    step_results = []
    for name, content in artifacts.items():
        step = Step(
            action=f"write {name}", provider_hint="chat", expected_artifact=name
        )
        step_results.append(StepResult(step=step, raw_response={}, content=content))
        if project_dir is not None:
            path = project_dir / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return ExecutionReport(
        intent="test",
        step_results=step_results,
        assumptions=["ok"],
        provenance={},
        artifacts={},
        plan=Plan(
            assumption="ok", confidence=0.9, steps=[sr.step for sr in step_results]
        ),
    )


def test_loop_stops_at_max_iterations(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=2)

    report = _make_report({})
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert len(result.iterations) == 2
    assert result.final_decision == "stop"
    assert "max iterations" in result.summary.lower()


def test_loop_stops_on_done_callback(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10)

    # Pre-seed an existing file so the new file does not breach the refactor tax.
    existing = tmp_path / "src" / "existing.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# existing\n_ROOT_KNOT = object()\n", encoding="utf-8")

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run(
                "add a feature",
                done_callback=lambda _it: True,
            )

    assert len(result.iterations) == 1
    assert result.final_decision == "done"


def test_loop_blocks_done_on_refactor_tax_breach(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10)

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=None
    )

    def _write_and_return(*_args, **_kwargs):
        # Simulate run_rootact writing the artifact during the iteration.
        for step in report.step_results:
            path = tmp_path / step.step.expected_artifact
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(step.content, encoding="utf-8")
        return Rooted(value=report, assumption="ok", confidence=0.9)

    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=_write_and_return,
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run(
                "add a feature",
                done_callback=lambda _it: True,
            )

    assert len(result.iterations) == 1
    assert result.final_decision == "stop"
    assert "refactor tax" in result.summary.lower()


def test_loop_allows_done_with_allow_debt(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10, allow_debt=True)

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run(
                "add a feature",
                done_callback=lambda _it: True,
            )

    assert len(result.iterations) == 1
    assert result.final_decision == "done"


def test_loop_detects_missing_root_knot(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10)

    report = _make_report({"src/foo.py": "# code without knot\n"}, project_dir=tmp_path)
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "regression"
    assert "src/foo.py" in result.iterations[0].knot_status["missing_knot"]


def test_loop_ignores_non_python_artifacts_in_knot_check(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=1)

    report = _make_report(
        {
            "src/foo.py": "# code\n_ROOT_KNOT = object()\n",
            "test_results.txt": "3 passed\n",
        },
        project_dir=tmp_path,
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision != "regression"
    assert "test_results.txt" not in result.iterations[0].knot_status["checked_files"]


def test_loop_detects_test_failure(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10)

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(
            controller,
            "_run_tests",
            return_value=(
                1,
                "1 failed",
                "FAILED tests/test_foo.py::test_x - assertion error",
            ),
        ):
            result = controller.run("add a feature")

    assert result.final_decision == "regression"
    assert result.iterations[0].test_returncode == 1


def test_loop_detects_intent_oscillation(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=5)

    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    foo = src_dir / "foo.py"
    foo.write_text("def old(): pass\n_ROOT_KNOT = object()\n", encoding="utf-8")

    def alternating_report(_config, _intent, **_kwargs):
        text = foo.read_text(encoding="utf-8")
        if "def old():" in text:
            new_content = "def new(): pass\n_ROOT_KNOT = object()\n"
        else:
            new_content = "def old(): pass\n_ROOT_KNOT = object()\n"
        foo.write_text(new_content, encoding="utf-8")
        report = ExecutionReport(
            intent="test",
            step_results=[
                StepResult(
                    step=Step(
                        action="update foo",
                        provider_hint="chat",
                        expected_artifact="src/foo.py",
                    ),
                    raw_response={},
                    content=new_content,
                )
            ],
            assumptions=["ok"],
            provenance={},
            artifacts={},
            plan=Plan(
                assumption="ok",
                confidence=0.9,
                steps=[
                    Step(
                        action="update foo",
                        provider_hint="chat",
                        expected_artifact="src/foo.py",
                    )
                ],
            ),
        )
        return Rooted(value=report, assumption="ok", confidence=0.9)

    with patch("rootact.loop_controller.run_rootact", side_effect=alternating_report):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("rename old to new")

    assert result.final_decision == "regression"
    assert len(result.iterations) >= 2


def test_loop_detects_quality_regression(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=10)

    first = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )
    # Second iteration has lower confidence, so quality score drops.
    second = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(
                step=Step(
                    action="write src/foo.py",
                    provider_hint="chat",
                    expected_artifact="src/foo.py",
                ),
                raw_response={},
                content="# code\n_ROOT_KNOT = object()\n",
            )
        ],
        assumptions=["ok"],
        provenance={},
        artifacts={},
        plan=Plan(
            assumption="ok",
            confidence=0.1,
            steps=[
                Step(
                    action="write src/foo.py",
                    provider_hint="chat",
                    expected_artifact="src/foo.py",
                )
            ],
        ),
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=[
            Rooted(value=first, assumption="ok", confidence=0.9),
            Rooted(value=second, assumption="ok", confidence=0.1),
        ],
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert len(result.iterations) == 2
    assert result.final_decision == "regression"
    assert "regressed" in result.iterations[1].reflection


def test_loop_continues_when_all_gates_pass(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=3)

    # Each iteration produces the same file with different content so the loop
    # does not flag the run as stagnant on content identity alone.
    reports = [
        _make_report(
            {"src/foo.py": f"# code iter {i}\n_ROOT_KNOT = object()\n"},
            project_dir=tmp_path,
        )
        for i in range(1, 4)
    ]
    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=[
            Rooted(value=report, assumption="ok", confidence=0.9) for report in reports
        ],
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert len(result.iterations) == 3
    assert all(it.decision == "continue" for it in result.iterations[:-1])
    assert result.iterations[-1].decision == "stop"


def test_write_report_persists_loop_result(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=1)

    report = _make_report({})
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    report_path = controller.write_report(result)
    assert report_path.is_file()
    text = report_path.read_text(encoding="utf-8")
    assert "final_decision" in text
    assert "iterations" in text


def test_loop_with_planner_returns_done_when_backlog_complete(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    planner = MagicMock()
    planner.load.return_value = [
        Milestone(id="m1", description="done", acceptance="done", status="done")
    ]
    controller = LoopController(config_path, max_iterations=10, planner=planner)

    result = controller.run("add a feature")

    assert result.final_decision == "done"
    assert len(result.iterations) == 0
    assert "All milestones completed" in result.summary


def test_loop_with_planner_advances_through_milestones(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    planner = MagicMock()
    planner.load.return_value = [
        Milestone(id="m1", description="first", acceptance="produce src/foo1.py"),
        Milestone(id="m2", description="second", acceptance="produce src/foo2.py"),
    ]
    controller = LoopController(config_path, max_iterations=10, planner=planner)

    reports = [
        _make_report(
            {f"src/foo{i}.py": f"# iter {i}\n_ROOT_KNOT = object()\n"},
            project_dir=tmp_path,
        )
        for i in range(1, 3)
    ]
    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=[
            Rooted(value=report, assumption="ok", confidence=0.9) for report in reports
        ],
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "done"
    assert len(result.iterations) == 2
    planner.save.assert_called()


def test_loop_with_planner_generates_backlog_when_missing(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[Milestone(id="m1", description="only", acceptance="produce src/foo.py")],
        assumption="ok",
        confidence=0.9,
    )
    controller = LoopController(config_path, max_iterations=10, planner=planner)

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    planner.generate_backlog.assert_called_once()
    planner.save.assert_called()
    assert result.final_decision == "done"


def test_loop_uses_custom_test_command(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(
        config_path,
        max_iterations=1,
        test_command=["-m", "pytest", "-q", "--tb=short"],
    )

    report = _make_report({})
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(
            controller, "_run_tests", wraps=controller._run_tests
        ) as run_tests:
            controller.run("add a feature")

    assert run_tests.call_count == 1


def test_loop_reports_iteration_timeout_as_regression(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=2, iteration_timeout=0.01)

    def _slow_run(*_args, **_kwargs):
        import time

        time.sleep(1.0)
        return Rooted(value=_make_report({}), assumption="ok", confidence=0.9)

    with patch("rootact.loop_controller.run_rootact", side_effect=_slow_run):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "regression"
    assert result.iterations[0].error is not None
    assert "timed out" in result.iterations[0].error.lower()


def test_loop_feedback_includes_error_and_missing_knot(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=2)

    previous = LoopIteration(
        index=1,
        intent="first",
        report=None,
        test_returncode=1,
        test_summary="1 failed",
        test_output="FAILED tests/test_foo.py::test_x - assertion error",
        knot_status={
            "checked_files": ["src/foo.py"],
            "missing_knot": ["src/foo.py"],
            "all_knotted": False,
        },
        quality_score=0.0,
        reflection="tests failed",
        decision="regression",
        error="provider refused",
        assumptions=[],
    )
    augmented = controller._augment_intent("add a feature", [previous], None)
    assert "provider refused" in augmented
    assert "test summary: 1 failed" in augmented
    assert "src/foo.py" in augmented


def test_write_report_includes_error_and_assumptions(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=1)

    report = _make_report({"src/foo.py": "# code\n_ROOT_KNOT = object()\n"})
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    report_path = controller.write_report(result)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert "error" in data["iterations"][0]
    assert "assumptions" in data["iterations"][0]
    assert data["iterations"][0]["assumptions"] == ["ok"]


def test_loop_falls_back_to_no_milestone_mode_when_backlog_generation_fails(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=None,
        assumption="planner is healthy",
        confidence=0.0,
        error="planner refused",
    )
    controller = LoopController(config_path, max_iterations=2, planner=planner)

    report = _make_report({})
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "2 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "stop"
    assert len(result.iterations) == 2


def test_loop_attempts_repair_when_tests_fail(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(
        config_path,
        max_iterations=2,
        repair_attempts=1,
    )

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    failing_output = (
        "FAILED tests/test_foo.py::test_one - AssertionError: assert 1 == 2\n"
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(
            controller,
            "_run_tests",
            side_effect=[
                (1, "1 failed", failing_output),
                (0, "1 passed", ""),
            ],
        ):
            result = controller.run("add a feature")

    # The first iteration should fail tests but continue into a repair iteration.
    assert result.iterations[0].decision == "continue"
    assert result.iterations[0].test_returncode == 1
    # The second iteration should use the repair intent.
    assert "REPAIR ITERATION" in result.iterations[1].intent
    assert result.iterations[1].test_returncode == 0
    assert result.final_decision == "stop"


def test_diversity_prompt_injected_after_tunneling(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(config_path, tunneling_limit=2)
    controller.backlog = [
        Milestone(
            id="m1",
            description="Add fixture registry",
            acceptance="registry exists",
            status="done",
        ),
        Milestone(
            id="m2",
            description="Add edge-case fixture builder",
            acceptance="builder exists",
            status="done",
        ),
    ]
    controller._completed_families = ["test-fixtures", "test-fixtures"]

    current = Milestone(
        id="m3",
        description="Add fixture validator",
        acceptance="validator exists",
        status="open",
    )
    intent = controller._augment_intent("implement the milestone", [], current)

    assert "[DIVERSITY PROMPT]" in intent
    assert "test-fixtures" in intent


def test_error_memory_included_in_augmented_intent(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(config_path)
    controller._error_memory.record(
        SimpleNamespace(
            index=1,
            test_output=(
                "FAILED tests/test_foo.py::test_one - AssertionError: assert 1 == 2"
            ),
            error="",
            reflection="",
            knot_status={"missing_knot": []},
        )
    )

    intent = controller._augment_intent("do work", [], None)
    assert "[Error memory" in intent
    assert "test_foo.py::test_one" in intent


def test_strategic_context_clear_after_stagnant_streak(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(
        config_path,
        max_iterations=6,
        strategic_clear_threshold=2,
    )

    # Identical reports produce stagnant decisions, which stack into a streak.
    stuck_report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    unstuck_report = _make_report(
        {"src/bar.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=[
            Rooted(value=stuck_report, assumption="ok", confidence=0.9),
            Rooted(value=stuck_report, assumption="ok", confidence=0.9),
            Rooted(value=stuck_report, assumption="ok", confidence=0.9),
            Rooted(value=unstuck_report, assumption="ok", confidence=0.9),
        ],
    ):
        with patch.object(
            controller, "_run_tests", return_value=(0, "1 passed", "")
        ) as mock_tests:
            result = controller.run(
                "add a feature",
                done_callback=lambda it: it.index == 4,
            )

    assert result.final_decision == "done"
    assert len(result.iterations) == 4
    assert "STRATEGIC CONTEXT CLEAR" in result.iterations[3].intent
    assert mock_tests.call_count == 4
    assert controller._error_memory.summarize() == ""


def test_lint_repair_queues_when_tests_pass_but_lint_fails(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    src = tmp_path / "src"
    src.mkdir()
    (src / "dirty.py").write_text("import os\n\ndef hello(): pass\n", encoding="utf-8")

    controller = LoopController(
        config_path,
        max_iterations=3,
        repair_attempts=1,
        python_executable=sys.executable,
    )

    report = _make_report(
        {"src/dirty.py": "import os\n_ROOT_KNOT = object()\ndef hello(): pass\n"},
        project_dir=tmp_path,
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add a feature")

    assert result.iterations[0].decision == "continue"
    assert "LINT/FIX ITERATION" in result.iterations[1].intent
    assert result.final_decision == "stop"


def test_preflight_repair_skips_pytest_for_invalid_test(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(
        config_path,
        max_iterations=3,
        repair_attempts=1,
    )

    bad_test = "def test_foo():\n    assert re.match('x', 'x')\n_ROOT_KNOT = object()\n"
    fixed_test = (
        "import re\n"
        "def test_foo():\n"
        "    assert re.match('x', 'x')\n"
        "_ROOT_KNOT = object()\n"
    )
    bad_report = _make_report(
        {"tests/test_foo.py": bad_test},
        project_dir=tmp_path,
    )
    fixed_report = _make_report(
        {"tests/test_foo.py": fixed_test},
        project_dir=tmp_path,
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        side_effect=[
            Rooted(value=bad_report, assumption="ok", confidence=0.9),
            Rooted(value=fixed_report, assumption="ok", confidence=0.9),
        ],
    ):
        with patch.object(
            controller, "_run_tests", return_value=(0, "1 passed", "")
        ) as mock_tests:
            result = controller.run(
                "add a feature",
                done_callback=lambda it: it.test_returncode == 0,
            )

    assert result.iterations[0].decision == "continue"
    assert result.iterations[0].test_summary == "preflight validation failed"
    assert "PREFLIGHT REPAIR" in result.iterations[1].intent
    assert mock_tests.call_count == 1
    assert result.final_decision == "done"


def test_write_report_includes_metrics_rollup(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=1)

    report = _make_report({"src/foo.py": "# code\n_ROOT_KNOT = object()\n"})
    report.metrics["total_input_tokens"] = 100
    report.metrics["total_output_tokens"] = 50
    report.metrics["total_tokens"] = 150
    report.metrics["total_cost"] = 0.0002
    report.metrics["total_latency_ms"] = 42

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add a feature")

    assert result.iterations[0].metrics["total_tokens"] == 150
    report_path = controller.write_report(result)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["metrics"]["total_tokens"] == 150
    assert data["metrics"]["total_cost"] == 0.0002
    assert data["iterations"][0]["metrics"]["total_tokens"] == 150


def test_run_with_timeout_returns_rooted_timeout(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, iteration_timeout=0.01)

    def slow_run(*_args, **_kwargs):
        import time

        time.sleep(0.5)
        return Rooted(
            value=None, error="should not reach", assumption="", confidence=0.0
        )

    with patch("rootact.loop_controller.run_rootact", side_effect=slow_run):
        result = controller._run_with_timeout("intent")

    assert not result.is_ok()
    assert "timed out" in (result.error or "").lower()


def test_build_strategic_clear_intent_contains_original_intent(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, strategic_clear_threshold=2)
    intent = controller._build_strategic_clear_intent("stagnant", 5, "add feature")
    assert "STRATEGIC CONTEXT CLEAR" in intent
    assert "add feature" in intent
    assert "5" in intent


def test_summarize_empty_iterations(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    summary = controller._summarize([])
    assert "No iterations completed" in summary


def test_loop_handshakes_high_risk_milestone(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    from rootact.loop_planner import Milestone
    from rootact.milestone_oracle import MilestoneOracle
    from rootact.progress_oracle import ProgressVerdict, ROOT_KNOT

    milestone = Milestone(
        id="m1",
        description="deploy the service",
        acceptance="service is live",
    )
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[milestone], assumption="ok", confidence=0.9
    )

    oracle = MagicMock(spec=MilestoneOracle)
    oracle.evaluate.return_value = Rooted(
        value=ProgressVerdict(
            verdict="handshake",
            reason="high risk",
            confidence=1.0,
            knot=ROOT_KNOT,
        ),
        assumption="ok",
        confidence=1.0,
    )

    controller = LoopController(
        config_path,
        max_iterations=2,
        planner=planner,
        milestone_oracle=oracle,
    )

    existing = tmp_path / "src" / "existing.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# existing\n_ROOT_KNOT = object()\n", encoding="utf-8")
    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("deploy")

    assert result.final_decision == "done"
    assert "m1" in result.handshake_milestones


def test_loop_regression_on_milestone_oracle_failure(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    from rootact.loop_planner import Milestone
    from rootact.milestone_oracle import MilestoneOracle

    milestone = Milestone(
        id="m1",
        description="core",
        acceptance="works",
    )
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[milestone], assumption="ok", confidence=0.9
    )

    oracle = MagicMock(spec=MilestoneOracle)
    oracle.evaluate.return_value = Rooted(
        value=None,
        assumption="ok",
        confidence=0.0,
        error="oracle failed",
    )

    controller = LoopController(
        config_path,
        max_iterations=2,
        planner=planner,
        milestone_oracle=oracle,
    )

    existing = tmp_path / "src" / "existing.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# existing\n_ROOT_KNOT = object()\n", encoding="utf-8")
    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add feature")

    assert result.final_decision == "regression"
    assert "oracle failed" in result.summary


def test_loop_uses_string_test_command(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(
        config_path,
        max_iterations=1,
        test_command="-m pytest -q",
    )
    assert controller.test_command == ["-m pytest -q"]


def test_take_snapshot_skips_pycache_and_handles_errors(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    controller.project_dir = tmp_path

    src = tmp_path / "src"
    src.mkdir()
    (src / "clean.py").write_text("_ROOT_KNOT = object()\n", encoding="utf-8")
    pycache = src / "__pycache__"
    pycache.mkdir()
    (pycache / "junk.py").write_text("bad\n", encoding="utf-8")

    snapshot = controller._take_snapshot()
    assert any(key.endswith("clean.py") for key in snapshot)
    assert not any("__pycache__" in key for key in snapshot)

    with patch.object(Path, "read_text", side_effect=OSError("denied")):
        assert controller._take_snapshot() == {}


def test_plan_report_assumption_used_as_loop_assumption(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=1)

    plan = Plan(assumption="plan assumption", confidence=0.8, steps=[])
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=plan, assumption="ok", confidence=0.8),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("plan something")

    assert result.iterations[0].assumptions == ["plan assumption"]


def test_preflight_repair_exhausted_returns_regression(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(
        config_path,
        max_iterations=2,
        repair_attempts=0,
    )

    bad_test = "def test_foo():\n    assert re.match('x', 'x')\n_ROOT_KNOT = object()\n"
    bad_report = _make_report(
        {"tests/test_foo.py": bad_test},
        project_dir=tmp_path,
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=bad_report, assumption="ok", confidence=0.9),
    ):
        result = controller.run("add a feature")

    assert result.final_decision == "regression"
    assert "missing imports" in result.summary.lower()


def test_stagnation_limit_triggers_stop(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(
        config_path,
        max_iterations=10,
        stagnation_limit=2,
    )

    stuck_report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=stuck_report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "stop"
    assert "no meaningful progress" in result.summary.lower()


def test_milestone_verdict_wrong_knot_returns_regression(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    from rootact.loop_planner import Milestone
    from rootact.milestone_oracle import MilestoneOracle

    milestone = Milestone(id="m1", description="core", acceptance="works")
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[milestone], assumption="ok", confidence=0.9
    )

    oracle = MagicMock(spec=MilestoneOracle)
    oracle.evaluate.return_value = Rooted(
        value=SimpleNamespace(
            verdict="proceed",
            reason="ok",
            confidence=1.0,
            knot=object(),  # wrong knot
        ),
        assumption="ok",
        confidence=1.0,
    )

    controller = LoopController(
        config_path,
        max_iterations=2,
        planner=planner,
        milestone_oracle=oracle,
    )
    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add feature")

    assert result.final_decision == "regression"
    assert "missing canonical Root Knot" in result.summary


def test_handshake_registry_persists_high_risk_milestone(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    from rootact.handshake_registry import HandshakeRegistry
    from rootact.loop_planner import Milestone
    from rootact.milestone_oracle import MilestoneOracle
    from rootact.progress_oracle import ProgressVerdict, ROOT_KNOT

    milestone = Milestone(
        id="m1",
        description="deploy the service",
        acceptance="service is live",
    )
    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[milestone], assumption="ok", confidence=0.9
    )

    oracle = MagicMock(spec=MilestoneOracle)
    oracle.evaluate.return_value = Rooted(
        value=ProgressVerdict(
            verdict="handshake",
            reason="high risk",
            confidence=1.0,
            knot=ROOT_KNOT,
        ),
        assumption="ok",
        confidence=1.0,
    )

    registry = HandshakeRegistry(tmp_path)
    controller = LoopController(
        config_path,
        max_iterations=2,
        planner=planner,
        milestone_oracle=oracle,
        handshake_registry=registry,
    )

    existing = tmp_path / "src" / "existing.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# existing\n_ROOT_KNOT = object()\n", encoding="utf-8")
    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"}, project_dir=tmp_path
    )

    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("deploy")

    assert result.final_decision == "done"
    assert "m1" in result.handshake_milestones
    assert registry.pending()[0].id == "m1"


def test_reflection_includes_ledger_message(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    reflection = controller._reflect(
        index=3,
        error=None,
        test_returncode=0,
        knot_status={"all_knotted": True, "missing_knot": []},
        quality_score=0.9,
        previous_score=0.8,
        ledger_message="refactor tax breach",
    )
    assert "refactor ledger: refactor tax breach" in reflection


def test_run_tests_handles_timeouts_and_missing_python(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")

    controller = LoopController(config_path, python_executable="missing_python_xyz")
    rc, summary, output = controller._run_tests()
    assert rc is None
    assert "unavailable" in summary

    controller2 = LoopController(config_path, python_executable=sys.executable)
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300)):
        rc2, summary2, _ = controller2._run_tests()
    assert rc2 is None
    assert "timed out" in summary2


def test_check_root_knot_flags_missing_file(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)

    report = _make_report({"src/missing.py": "# code\n_ROOT_KNOT = object()\n"})
    status = controller._check_root_knot(report)
    assert status["missing_knot"] == ["src/missing.py"]


def test_compute_quality_score_for_plan(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    plan = Plan(assumption="ok", confidence=0.95, steps=[])
    score = controller._compute_quality_score(plan)
    assert 0.0 <= score <= 1.0


def test_report_fingerprint_returns_none_for_plan(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    plan = Plan(assumption="ok", confidence=0.9, steps=[])
    assert controller._report_fingerprint(plan) is None


def test_quality_floor_triggers_regression(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(
        config_path,
        max_iterations=1,
        quality_floor=0.99,
    )

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.5),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add a feature")

    assert result.final_decision == "regression"


def test_stagnant_decision_on_identical_iterations(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=3, stagnation_limit=1)

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            result = controller.run("add a feature")

    assert result.iterations[1].decision == "stagnant"


def test_attempt_repair_returns_false_without_output(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, repair_attempts=1)

    iteration = LoopIteration(
        index=1,
        intent="test",
        report=None,
        test_returncode=1,
        test_summary="failed",
        test_output="",
        knot_status={"all_knotted": True},
        quality_score=0.0,
        reflection="",
        decision="continue",
    )
    assert not controller._attempt_repair(iteration)


def test_attempt_lint_repair_no_issues_returns_false(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, repair_attempts=1)
    assert not controller._attempt_lint_repair()


def test_attempt_lint_repair_bad_prompt_rooted_returns_false(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, repair_attempts=1)

    with patch.object(controller._lint_repair, "check") as mock_check:
        mock_check.return_value = MagicMock(passed=False)
        with patch.object(
            controller._lint_repair,
            "build_repair_prompt",
            return_value=Rooted(
                value=None,
                error="bad",
                assumption="",
                confidence=0.0,
            ),
        ):
            assert not controller._attempt_lint_repair()


def test_take_snapshot_returns_empty_when_project_dir_is_not_a_directory(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    # Make project_dir point to a file so .is_dir() is False.
    not_dir = tmp_path / "not_a_dir"
    not_dir.write_text("x", encoding="utf-8")
    controller.project_dir = not_dir
    assert controller._take_snapshot() == {}


def test_milestone_oracle_stop_verdict_ends_loop(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, max_iterations=3)
    controller.backlog = [
        Milestone(
            id="m1",
            description="stop now",
            acceptance="never",
            status="open",
        )
    ]

    report = _make_report(
        {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
        project_dir=tmp_path,
    )
    from rootact.progress_oracle import ProgressVerdict, ROOT_KNOT

    stop_verdict = ProgressVerdict(
        verdict="stop", reason="oracle says stop", confidence=1.0, knot=ROOT_KNOT
    )
    with patch(
        "rootact.loop_controller.run_rootact",
        return_value=Rooted(value=report, assumption="ok", confidence=0.9),
    ):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            with patch.object(
                controller.milestone_oracle,
                "evaluate",
                return_value=Rooted(
                    value=stop_verdict, assumption="ok", confidence=1.0
                ),
            ):
                result = controller.run("add a feature")

    assert result.final_decision == "stop"
    assert "oracle stopped" in result.summary.lower()


def test_format_backlog_returns_empty_string_when_backlog_is_none(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    controller.backlog = None
    assert controller._format_backlog() == ""


def test_check_root_knot_skips_empty_artifact_path(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    controller.project_dir = tmp_path
    step = Step(action="noop", provider_hint="chat", expected_artifact="")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="")],
        assumptions=["ok"],
        provenance={},
        artifacts={},
        plan=Plan(assumption="ok", confidence=0.9, steps=[step]),
    )
    status = controller._check_root_knot(report)
    assert status["checked_files"] == []
    assert status["missing_knot"] == []
    assert status["all_knotted"] is True


def test_decide_next_action_regression_on_score_decrease(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path)
    current = LoopIteration(
        index=2,
        intent="test",
        report=_make_report(
            {"src/foo.py": "# code\n_ROOT_KNOT = object()\n"},
            project_dir=tmp_path,
        ),
        test_returncode=0,
        test_summary="1 passed",
        test_output="",
        knot_status={"all_knotted": True, "checked_files": ["src/foo.py"]},
        quality_score=0.5,
        reflection="",
        decision="continue",
    )
    previous = LoopIteration(
        index=1,
        intent="test",
        report=current.report,
        test_returncode=0,
        test_summary="1 passed",
        test_output="",
        knot_status={"all_knotted": True, "checked_files": ["src/foo.py"]},
        quality_score=0.9,
        reflection="",
        decision="continue",
    )
    decision = controller._decide(current, 0, None, previous)
    assert decision == "regression"


def test_attempt_repair_returns_false_when_diagnoser_fails(tmp_path):
    config_path = tmp_path / "rootact.yaml"
    config_path.write_text("project:\n  name: test\n", encoding="utf-8")
    controller = LoopController(config_path, repair_attempts=1)
    iteration = LoopIteration(
        index=1,
        intent="test",
        report=None,
        test_returncode=1,
        test_summary="failed",
        test_output="some output",
        knot_status={"all_knotted": True},
        quality_score=0.0,
        reflection="",
        decision="continue",
    )
    with patch.object(
        controller._failure_diagnoser,
        "diagnose",
        return_value=Rooted(
            value=None,
            error="could not diagnose",
            assumption="",
            confidence=0.0,
        ),
    ):
        assert not controller._attempt_repair(iteration)
