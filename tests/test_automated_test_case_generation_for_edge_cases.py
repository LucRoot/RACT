from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

from rootact.automated_test_case_generation_for_edge_cases import (
    AutomatedTestCaseGenerator,
    EdgeCaseTest,
)

_ROOT_KNOT = object()


def test_empty_story_returns_empty_list() -> None:
    generator = AutomatedTestCaseGenerator()
    assert generator.generate("") == []
    assert generator.generate("   ") == []


def test_input_signals_generate_empty_and_missing_tests() -> None:
    generator = AutomatedTestCaseGenerator()
    tests = generator.generate("Validate user input fields")
    descriptions = {t.description for t in tests}
    assert "empty input" in descriptions
    assert "missing required field" in descriptions


def test_size_signals_generate_boundary_tests() -> None:
    generator = AutomatedTestCaseGenerator()
    tests = generator.generate("Check file size limits")
    descriptions = {t.description for t in tests}
    assert "maximum allowed size" in descriptions
    assert "size exceeding limit" in descriptions


def test_numeric_signals_generate_zero_and_negative_tests() -> None:
    generator = AutomatedTestCaseGenerator()
    tests = generator.generate("Process payment amount")
    descriptions = {t.description for t in tests}
    assert "zero value" in descriptions
    assert "negative value" in descriptions


def test_unknown_story_generates_fallback_test() -> None:
    generator = AutomatedTestCaseGenerator()
    tests = generator.generate("foo bar baz qux")
    assert len(tests) == 1
    assert tests[0].description == "unexpected input type"


def test_edge_case_test_dataclass() -> None:
    test = EdgeCaseTest(description="x", inputs={"a": 1}, expected_output=2)
    assert test.description == "x"
    assert test.inputs == {"a": 1}
    assert test.expected_output == 2
    assert test.expected_error is None


# RACT 0.1.0 - Initial Public Release
