"""B-175 (WRIGHT, ADR-0049 D10): the model never ends the loop; the limit stops and asks.

Slice 1. A model's completion claim (a step that says TASK_COMPLETE) does not end the loop: only the
harness's done predicate does. At the iteration limit the result carries a question for the operator
(what ran, the last decision, the last test summary, the files the last round changed). The question
does not raise the limit; a continue choice is a later slice.

The provider is faked (run_ract patched) and the tests are not run (_run_tests patched), as in
tests/test_b122_loop_outcomes.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ract.core.loop import TerminationCause
from ract.executor import ExecutionReport, StepResult
from ract.loop_controller import LoopController
from ract.manager import Plan, Step
from ract.rooted import Rooted
from tests.test_loop_controller import _make_report


def _config(tmp_path: Path) -> Path:
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    return config


def _report_with_claim(project: Path, round_no: int) -> ExecutionReport:
    base = _make_report({"src/foo.py": f"# version {round_no}\n"}, project_dir=project)
    claim = StepResult(
        step=Step(action="say it is finished", provider_hint="chat", expected_artifact="claim"),
        raw_response={},
        content="TASK_COMPLETE. All tests pass. The task is done.",
    )
    return ExecutionReport(
        intent=base.intent,
        step_results=[*base.step_results, claim],
        assumptions=base.assumptions,
        provenance={},
        artifacts={},
        plan=Plan(assumption="ok", confidence=0.9, steps=[sr.step for sr in base.step_results] + [claim.step]),
    )


def _run(controller: LoopController, project: Path, *, done_callback) -> object:
    rounds = {"n": 0}

    def scripted_model(*_args, **_kwargs) -> Rooted:
        rounds["n"] += 1
        return Rooted(value=_report_with_claim(project, rounds["n"]), assumption="ok", confidence=0.9)

    with patch("ract.loop_controller.run_ract", MagicMock(side_effect=scripted_model)):
        with patch.object(controller, "_run_tests", return_value=(0, "1 passed", "")):
            return controller.run("add a feature", done_callback=done_callback)


def test_a_completion_claim_at_step_2_of_5_does_not_end_the_loop(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=5)
    seen: list[int] = []

    def done_only_at_five(iteration) -> bool:
        seen.append(iteration.index)
        return iteration.index == 5

    result = _run(controller, tmp_path, done_callback=done_only_at_five)
    assert seen == [1, 2, 3, 4, 5], "the loop stopped before the harness said done"
    assert result.final_decision == "done"
    assert result.cause is TerminationCause.COMPLETE
    assert len(result.iterations) == 5


def test_the_limit_stop_carries_a_question_and_what_was_done(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=3)
    result = _run(controller, tmp_path, done_callback=lambda _it: False)
    assert result.final_decision == "stop"
    assert result.cause is TerminationCause.BUDGET_EXHAUSTED
    question = result.limit_question
    assert question is not None, "the limit stop asks nothing"
    assert "max iterations (3)" in question
    assert "3 rounds ran" in question
    assert "foo.py" in question, "the question does not say what the last round changed"
    assert question.endswith("one more round of the same size?")


def test_a_stop_before_the_limit_asks_nothing(tmp_path: Path) -> None:
    controller = LoopController(_config(tmp_path), max_iterations=5)
    result = _run(controller, tmp_path, done_callback=lambda it: it.index == 2)
    assert result.final_decision == "done"
    assert result.limit_question is None
