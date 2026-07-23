"""Tests for preflight test validation."""

from __future__ import annotations


from ract.preflight_test_validator import (
    PreflightIssue,
    validate_report_tests,
    validate_test_content,
)


def test_valid_test_passes():
    content = "import re\ndef test_regex_match():\n    assert re.match(r'x', 'xyz')\n"
    rooted = validate_test_content("tests/test_foo.py", content)
    assert rooted.is_ok()


def test_syntax_error_fails():
    content = "def test_bad():\n    assert True\n    print("
    rooted = validate_test_content("tests/test_bad.py", content)
    assert not rooted.is_ok()
    assert "syntax error" in (rooted.error or "").lower()


def test_missing_re_import_fails():
    content = "def test_regex_match():\n    assert re.match(r'x', 'xyz')\n"
    rooted = validate_test_content("tests/test_foo.py", content)
    assert not rooted.is_ok()
    assert "missing imports" in (rooted.error or "").lower()
    assert "re" in (rooted.error or "")


def test_module_level_assert_missing_import_fails():
    content = "assert json.dumps({}) == '{}'\n"
    rooted = validate_test_content("tests/test_foo.py", content)
    assert not rooted.is_ok()
    assert "json" in (rooted.error or "")


def test_defined_symbol_does_not_flag_missing_import():
    content = "def re(x):\n    return x\ndef test_reuse():\n    assert re(1) == 1\n"
    rooted = validate_test_content("tests/test_foo.py", content)
    assert rooted.is_ok()


def test_non_test_artifact_is_ignored():
    content = "def test_regex_match():\n    assert re.match(r'x', 'xyz')\n"
    rooted = validate_test_content("src/foo.py", content)
    assert rooted.is_ok()


def test_validate_report_tests_filters_non_tests():
    from ract.executor import ExecutionReport, StepResult
    from ract.manager import Plan, Step

    step = Step(action="write", provider_hint="chat", expected_artifact="src/foo.py")
    report = ExecutionReport(
        intent="test",
        step_results=[StepResult(step=step, raw_response={}, content="x=1")],
        assumptions=["ok"],
        plan=Plan(assumption="ok", confidence=0.9, steps=[step]),
    )
    assert validate_report_tests(report) == []


def test_validate_report_tests_reports_test_issue():
    from ract.executor import ExecutionReport, StepResult
    from ract.manager import Plan, Step

    step = Step(
        action="write test", provider_hint="chat", expected_artifact="tests/test_foo.py"
    )
    report = ExecutionReport(
        intent="test",
        step_results=[
            StepResult(
                step=step,
                raw_response={},
                content="def test_foo():\n    assert re.match('x', 'x')\n",
            )
        ],
        assumptions=["ok"],
        plan=Plan(assumption="ok", confidence=0.9, steps=[step]),
    )
    issues = validate_report_tests(report)
    assert len(issues) == 1
    assert isinstance(issues[0], PreflightIssue)
    assert "re" in issues[0].message


# RACT 0.1.1 - Trust and tooling
