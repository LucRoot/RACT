"""B-112 screens: the tier-3 approval prompt, the structured test result and the verdict line
(ADR-0048 D6 and D10, decision package condition 4). Pure text at 80, 60 and 40 columns,
plain and rich. A control character in argv or a path is shown escaped, never raw.
"""

from __future__ import annotations

import re

import pytest

from ract.ui.command_screens import (
    CHOICES,
    TRACE_STATEMENT,
    CommandRequest,
    FailingTest,
    RunSummary,
    approval_prompt_lines,
    escape_controls,
    result_lines,
    verdict_lines,
)

WIDTHS = (80, 60, 40)
MARKUP = re.compile(r"\[/?bold\]")


def _flat(lines: list[str]) -> str:
    return " ".join(" ".join(MARKUP.sub("", line) for line in lines).split())


def _request(**overrides: object) -> CommandRequest:
    base = {
        "argv": ("python", "-m", "pytest", "tests/test_calc.py"),
        "executable": "C:/Python312/python.exe",
        "cwd": "src",
        "network": False,
        "sandbox_enforced": False,
        "env_names": ("PATH", "HOME"),
        "limits": "wall 900 s, 1 MiB per stream",
        "trust": "trusted",
        "reason": "run the calc tests",
    }
    base.update(overrides)
    return CommandRequest(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("rich", [False, True])
def test_the_prompt_fits_and_shows_each_field(width: int, rich: bool) -> None:
    lines = approval_prompt_lines(_request(), width, rich=rich)
    for line in lines:
        assert len(MARKUP.sub("", line)) <= width, line
    text = _flat(lines)
    assert "argv: python -m pytest tests/test_calc.py" in text
    assert "executable: C:/Python312/python.exe" in text
    assert "cwd: src" in text
    assert "network: off" in text
    assert "sandbox: best effort: not enforced on this machine" in text
    assert "environment names passed: PATH, HOME" in text
    assert " ".join(CHOICES.split()) in text


def test_the_prompt_says_when_the_sandbox_enforces() -> None:
    text = _flat(approval_prompt_lines(_request(sandbox_enforced=True), 80))
    assert "sandbox: enforced on this machine" in text


def test_the_model_reason_is_labelled_as_unchecked_model_text() -> None:
    text = _flat(approval_prompt_lines(_request(reason="delete the cache"), 80))
    assert "the model says (model text, not checked): delete the cache" in text


def test_control_characters_in_argv_and_paths_are_shown_escaped() -> None:
    lines = approval_prompt_lines(
        _request(argv=("evil\x1b[31m", "x\u202e"), cwd="a\x07b"), 80
    )
    joined = "\n".join(lines)
    assert "\x1b" not in joined and "\x07" not in joined and "\u202e" not in joined
    assert "\\x1b" in joined and "\\x07" in joined and "\\u202e" in joined


def test_escape_controls_keeps_plain_text() -> None:
    assert escape_controls("tests/test_calc.py") == "tests/test_calc.py"
    assert escape_controls("a\nb") == "a\\nb"


@pytest.mark.parametrize("width", WIDTHS)
def test_the_test_result_has_counts_time_exit_and_each_failure(width: int) -> None:
    summary = RunSummary(
        passed=11,
        failed=1,
        skipped=0,
        duration_s=3.24,
        exit_code=1,
        failing=(
            FailingTest(name="tests/test_calc.py::test_add", message="assert 1 == 2"),
        ),
    )
    lines = result_lines(summary, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "tests: 11 passed, 1 failed, 0 skipped (3.2 s, exit 1)" in text
    assert "failed: tests/test_calc.py::test_add" in text
    assert "assert 1 == 2" in text


def test_a_clean_run_shows_no_failure_lines() -> None:
    lines = result_lines(
        RunSummary(passed=3, failed=0, skipped=0, duration_s=0.5, exit_code=0), 80
    )
    assert len(lines) == 1 and "exit 0" in lines[0]


@pytest.mark.parametrize("width", WIDTHS)
def test_the_verdict_says_where_command_records_bind(width: int) -> None:
    lines = verdict_lines("passed, with 1 command run", 2, width)
    for line in lines:
        assert len(line) <= width, line
    text = _flat(lines)
    assert "verdict: passed, with 1 command run" in text
    assert "2 command records: " + TRACE_STATEMENT in text
    assert "not part of the signed Rootknot" in text


def test_the_trace_statement_is_the_adr_sentence() -> None:
    assert TRACE_STATEMENT == (
        "command records are in the trace; they are not part of the signed Rootknot"
    )


def test_a_verdict_with_no_command_run_places_no_records() -> None:
    lines = verdict_lines("Done: 1 step ran; no tests were run.", 0, 80)
    assert lines == ["verdict: Done: 1 step ran; no tests were run."]


def test_an_unparsed_runner_summary_says_counts_not_parsed() -> None:
    summary = RunSummary(
        passed=None, failed=None, skipped=None, duration_s=1.5, exit_code=2
    )
    text = _flat(result_lines(summary, 80))
    assert "tests: counts not parsed (1.5 s, exit 2)" in text
    assert "passed" not in text


def test_run_tests_parses_pytests_own_summary_line() -> None:
    """L-298 item 3: the counts come from pytest's last summary line, never guessed."""
    from ract.tools.tests_tool import pytest_summary

    out = (
        "FAILED tests/test_calc.py::test_add - assert 1 == 2\n"
        "==== 1 failed, 3 passed, 2 skipped in 0.42s ====\n"
    )
    summary = pytest_summary(out, 420, 1)
    assert (summary.passed, summary.failed, summary.skipped) == (3, 1, 2)
    assert summary.failing[0].name == "tests/test_calc.py::test_add"
    unknown = pytest_summary("ok\n", 100, 0)
    assert unknown.passed is None and unknown.failed is None
