"""B-122 (D-122): every termination cause has an outcome word and an exit code,
and the legacy ``--loop`` controller names the cause of each stop.

The provider is faked (``run_ract`` patched) and the project's tests are not
run (``_run_tests`` patched), as in tests/test_loop_controller.py.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ract.core.loop import OUTCOMES, TerminationCause, outcome_for
from ract.loop_controller import LoopController, LoopResult
from ract.rooted import Rooted
from tests.test_loop_controller import _make_report

D_122 = {
    "COMPLETE": ("done", 0),
    "REGRESSED": ("failed", 1),
    "PROVENANCE_FAILURE": ("refused", 3),
    "ASSUMPTION_BURST": ("failed", 1),
    "BUDGET_EXHAUSTED": ("budget", 4),
    "HANDSHAKE_BLOCKED": ("refused", 3),
    "PROVIDER_TIMEOUT": ("failed", 6),
    "PROMPT_DRIFT": ("refused", 3),
    "PROMPT_DIGEST_MISSING": ("refused", 3),
}


def test_every_cause_has_a_row_and_the_rows_are_d122() -> None:
    assert set(OUTCOMES) == set(TerminationCause)  # a new member needs a row
    assert {cause.name: outcome_for(cause) for cause in TerminationCause} == D_122


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    return config


def _run(controller: LoopController, tests=(0, "1 passed", ""), report=None, **kw):
    report = report or _make_report({})
    with patch(
        "ract.loop_controller.run_ract",
        kw.pop("run_ract", None)
        or MagicMock(
            return_value=Rooted(value=report, assumption="ok", confidence=0.9)
        ),
    ):
        with patch.object(controller, "_run_tests", return_value=tests):
            return controller.run("add a feature", **kw)


def test_t1_done(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=5)
    report = _make_report({"src/foo.py": "# code\n"}, project_dir=tmp_path)
    result = _run(controller, report=report, done_callback=lambda _it: True)
    assert result.final_decision == "done" and result.cause is TerminationCause.COMPLETE


def test_t2_a_failing_test_with_no_repair_left(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=5)
    controller.repair_attempts_remaining = 0
    report = _make_report({"src/foo.py": "# code\n"}, project_dir=tmp_path)
    result = _run(controller, tests=(1, "1 failed", "FAILED x"), report=report)
    assert result.final_decision == "regression"
    assert result.cause is TerminationCause.REGRESSED


def test_t3_a_milestone_verdict_without_its_sentinel(tmp_path: Path) -> None:
    from ract.loop_planner import Milestone
    from ract.milestone_oracle import MilestoneOracle

    planner = MagicMock()
    planner.load.return_value = None
    planner.generate_backlog.return_value = Rooted(
        value=[Milestone(id="m1", description="core", acceptance="works")],
        assumption="ok",
        confidence=0.9,
    )
    oracle = MagicMock(spec=MilestoneOracle)
    oracle.evaluate.return_value = Rooted(
        value=SimpleNamespace(
            verdict="proceed", reason="ok", confidence=1.0, knot=object()
        ),
        assumption="ok",
        confidence=1.0,
    )
    controller = LoopController(
        _config(tmp_path), max_iterations=2, planner=planner, milestone_oracle=oracle
    )
    report = _make_report({"src/foo.py": "# code\n"}, project_dir=tmp_path)
    result = _run(controller, report=report)
    assert result.cause is TerminationCause.PROVENANCE_FAILURE


def test_t5_the_iteration_limit(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=2)
    result = _run(controller)
    assert result.final_decision == "stop"
    assert result.cause is TerminationCause.BUDGET_EXHAUSTED


def test_t5_stagnation(tmp_path: Path) -> None:
    controller = LoopController(
        _config(tmp_path), max_iterations=10, stagnation_limit=2
    )
    report = _make_report({"src/foo.py": "# code\n"}, project_dir=tmp_path)
    result = _run(controller, report=report)
    assert "no meaningful progress" in result.summary.lower()
    assert result.cause is TerminationCause.BUDGET_EXHAUSTED


def test_t7_a_provider_call_that_timed_out(tmp_path: Path) -> None:
    controller = LoopController(
        _config(tmp_path), max_iterations=2, iteration_timeout=0.01
    )

    def slow(*_a, **_kw):
        time.sleep(0.5)
        return Rooted(value=_make_report({}), assumption="ok", confidence=0.9)

    result = _run(controller, run_ract=MagicMock(side_effect=slow))
    assert result.final_decision == "regression"
    assert result.cause is TerminationCause.PROVIDER_TIMEOUT


@pytest.mark.parametrize(
    "flag, cause",
    [
        ("t8_prompt_drift", TerminationCause.PROMPT_DRIFT),
        ("t9_prompt_digest_missing", TerminationCause.PROMPT_DIGEST_MISSING),
    ],
)
def test_t8_and_t9_name_their_own_cause(tmp_path: Path, flag: str, cause) -> None:
    from ract.loop_controller import LoopIteration

    controller = LoopController(_config(tmp_path), max_iterations=2)
    halt = LoopIteration(
        index=1,
        intent="add a feature",
        report=None,
        test_returncode=None,
        test_summary=flag,
        test_output="",
        quality_score=0.0,
        reflection=flag,
        decision="regression",
        error=None,
        assumptions=[],
        metrics={flag: True},
    )
    with patch.object(controller, "_check_prompt_drift", return_value=halt):
        result = _run(controller)
    assert result.cause is cause


def _cli(monkeypatch, tmp_path: Path, result: LoopResult, *extra: str) -> int:
    from ract import cli

    config = _config(tmp_path)

    class Controller:
        def __init__(self, *_a, **_kw) -> None:
            pass

        def run(self, _intent):
            return result

        def write_report(self, _result):
            return tmp_path / "report.json"

    monkeypatch.setattr("ract.loop_controller.LoopController", Controller)
    monkeypatch.setattr("ract.trust.confirm_loop", lambda *_a, **_kw: True)
    return cli.main(["run", "--config", str(config), "--loop", *extra, "do it"])


@pytest.mark.parametrize("cause", list(TerminationCause), ids=lambda c: c.name)
def test_ract_run_loop_yolo_exits_with_the_causes_code(
    monkeypatch, tmp_path: Path, capsys, cause
) -> None:
    result = LoopResult(
        iterations=[],
        final_decision="stop",
        summary="s",
        handshake_milestones=[],
        cause=cause,
    )
    assert _cli(monkeypatch, tmp_path, result, "--yolo") == outcome_for(cause)[1]
    assert f"halt: T{cause.value} {cause.name}" in capsys.readouterr().out


def test_ract_run_loop_without_yolo_still_refuses(monkeypatch, tmp_path: Path) -> None:
    result = LoopResult(
        iterations=[],
        final_decision="done",
        summary="s",
        handshake_milestones=[],
        cause=TerminationCause.COMPLETE,
    )
    assert _cli(monkeypatch, tmp_path, result) == 3  # D-104
