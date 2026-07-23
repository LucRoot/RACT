# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import sys

import pytest
from ract.test_failure_diagnoser import (
    FailureCase,
    RepairIntent,
    TestFailureDiagnoser,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project with a failing test."""
    src = tmp_path / "src"
    src.mkdir()
    lib = src / "calc.py"
    lib.write_text(
        "# Rooted by Dr. Lucas Root, Ph.D.\n"
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "\n"
        "_ROOT_KNOT = object()\n"
        "\n"
        "def add(a, b):\n"
        "    return a - b\n"  # intentionally wrong
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_calc.py"
    test_file.write_text(
        "# Rooted by Dr. Lucas Root, Ph.D.\n"
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "\n"
        "_ROOT_KNOT = object()\n"
        "\n"
        "from src.calc import add\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
    )
    return tmp_path


def test_parse_failures_from_summary():
    output = (
        "tests/test_alpha.py::test_one PASSED\n"
        "tests/test_alpha.py::test_two FAILED\n"
        "tests/test_beta.py::TestGroup::test_three ERROR\n"
    )
    diagnoser = TestFailureDiagnoser("/tmp")
    failures = diagnoser._parse_failures(output)
    assert len(failures) == 2
    assert failures[0].test_file == "tests/test_alpha.py"
    assert failures[0].test_function == "test_two"
    assert failures[1].test_file == "tests/test_beta.py"
    assert failures[1].test_function == "TestGroup::test_three"


def test_parse_failures_with_traceback(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project, python_executable=sys.executable)
    rc, output = diagnoser.capture_with_traceback(["-q", "tests"])
    assert rc != 0
    failures = diagnoser._parse_failures(output)
    assert len(failures) == 1
    failure = failures[0]
    assert failure.test_file == "tests/test_calc.py"
    assert failure.test_function == "test_add"
    assert failure.source_file == "src/calc.py"


def test_rank_files_prefers_source_over_test(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project, python_executable=sys.executable)
    rc, output = diagnoser.capture_with_traceback(["-q", "tests"])
    assert rc != 0
    failures = diagnoser._parse_failures(output)
    files = diagnoser._rank_files(failures)
    assert "src/calc.py" in files
    assert "tests/test_calc.py" in files
    assert files.index("src/calc.py") < files.index("tests/test_calc.py")


def test_diagnose_returns_repair_intent(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project, python_executable=sys.executable)
    rc, output = diagnoser.capture_with_traceback(["-q", "tests"])
    assert rc != 0
    rooted = diagnoser.diagnose(output)
    assert rooted.is_ok()
    intent = rooted.unwrap()
    assert isinstance(intent, RepairIntent)
    assert "1 failing test" in intent.summary
    assert "tests/test_calc.py::test_add" in intent.failing_tests
    assert "src/calc.py" in intent.relevant_files
    assert "Diagnose the root cause" in intent.prompt


def test_diagnose_empty_output_returns_error():
    diagnoser = TestFailureDiagnoser("/tmp")
    rooted = diagnoser.diagnose("no failures here")
    assert not rooted.is_ok()
    assert "No failing tests" in (rooted.error or "")


def test_build_repair_prompt_contains_instructions():
    failure = FailureCase(
        test_file="tests/test_x.py",
        test_function="test_x",
        source_file="src/x.py",
        line_number=7,
        error_type="AssertionError",
        error_message="expected 5, got 3",
    )
    diagnoser = TestFailureDiagnoser("/tmp")
    prompt = diagnoser._build_repair_prompt([failure], ["src/x.py", "tests/test_x.py"])
    assert "tests/test_x.py::test_x" in prompt
    assert "src/x.py" in prompt
    assert "preserve the root knot" in prompt.lower()


def test_capture_traceback_handles_missing_python(tmp_path):
    diagnoser = TestFailureDiagnoser(tmp_path, python_executable="/nonexistent/python")
    rc, output = diagnoser.capture_with_traceback()
    assert rc == -1
    assert "unavailable" in output


def test_parse_failure_headers_fallback():
    output = (
        "FAILED tests/test_alpha.py::test_one - assertion failed\n"
        "ERROR tests/test_beta.py::TestGroup::test_two - syntax error\n"
    )
    diagnoser = TestFailureDiagnoser("/tmp")
    failures = diagnoser._parse_failure_headers(output)
    assert len(failures) == 2
    assert failures[0].test_function == "test_one"
    assert failures[1].test_function == "TestGroup::test_two"


def test_parse_failures_falls_back_to_headers():
    output = "FAILED tests/test_alpha.py::test_one - assertion failed\n"
    diagnoser = TestFailureDiagnoser("/tmp")
    failures = diagnoser._parse_failures(output)
    assert len(failures) == 1
    assert failures[0].test_file == "tests/test_alpha.py"


def test_extract_failure_section_returns_full_output_when_no_match():
    diagnoser = TestFailureDiagnoser("/tmp")
    failure = FailureCase(test_file="tests/missing.py", test_function="test_x")
    section = diagnoser._extract_failure_section("some output", failure)
    assert section == "some output"


def test_infer_source_from_test_read_error(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    test_file = tests / "test_bad.py"
    test_file.write_bytes(b"\xff\xfe")
    diagnoser = TestFailureDiagnoser(tmp_path)
    assert diagnoser._infer_source_from_test("tests/test_bad.py") is None


def test_rank_files_with_already_relative_test_path(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project)
    failure = FailureCase(
        test_file="tests/test_calc.py",
        test_function="test_add",
        source_file="src/calc.py",
    )
    files = diagnoser._rank_files([failure])
    assert "tests/test_calc.py" in files
    assert "src/calc.py" in files


def test_extract_error_message(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project)
    section = "AssertionError: expected 5, got 3\n"
    error_type, error_message = diagnoser._extract_error_message(section)
    assert error_type == "AssertionError"
    assert "expected 5" in (error_message or "")


def test_build_repair_prompt_without_line_number():
    failure = FailureCase(
        test_file="tests/test_x.py",
        test_function="test_x",
        source_file="src/x.py",
    )
    diagnoser = TestFailureDiagnoser("/tmp")
    prompt = diagnoser._build_repair_prompt([failure], ["src/x.py"])
    assert "(source: src/x.py)" in prompt


def test_parse_failure_headers_skips_lines_without_node():
    output = "FAILED tests/test_alpha.py - assertion failed\n"
    diagnoser = TestFailureDiagnoser("/tmp")
    failures = diagnoser._parse_failure_headers(output)
    assert failures == []


def test_nearest_traceback_falls_back_to_last_frame(tmp_project):
    diagnoser = TestFailureDiagnoser(tmp_project)
    test_file = tmp_project / "tests" / "test_calc.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_x(): pass\n")
    section = f'File "{test_file}", line 5\nFile "{test_file}", line 7\n'
    source_file, line_number = diagnoser._nearest_traceback_source(section)
    assert source_file == "tests/test_calc.py"
    assert line_number == 7


def test_infer_source_from_test_with_multiple_imports(tmp_project):
    tests = tmp_project / "tests"
    tests.mkdir(exist_ok=True)
    test_file = tests / "test_multi.py"
    test_file.write_text(
        "import os, sys\nfrom src.calc import add\nimport src.calc as calc\n"
    )
    diagnoser = TestFailureDiagnoser(tmp_project)
    assert diagnoser._infer_source_from_test("tests/test_multi.py") == "src/calc.py"


def test_infer_source_from_test_returns_none_when_module_missing(tmp_project):
    tests = tmp_project / "tests"
    tests.mkdir(exist_ok=True)
    test_file = tests / "test_orphan.py"
    test_file.write_text("from src.missing import thing\n")
    diagnoser = TestFailureDiagnoser(tmp_project)
    assert diagnoser._infer_source_from_test("tests/test_orphan.py") is None


def test_relative_path_handles_os_error(tmp_path):
    diagnoser = TestFailureDiagnoser(tmp_path)
    assert diagnoser._relative_path("\x00invalid") is None


# RACT 0.1.1 - Trust and tooling
