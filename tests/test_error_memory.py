"""Tests for ErrorMemory failure-pattern summarization."""

from __future__ import annotations


from types import SimpleNamespace

import pytest

from ract.error_memory import ErrorMemory


@pytest.fixture
def memory(tmp_path):
    return ErrorMemory(tmp_path)


def test_record_extracts_timeout_pattern(memory):
    iteration = SimpleNamespace(
        index=2,
        test_output="",
        error="Iteration timed out after 30s.",
        reflection="",
    )
    patterns = memory.record(iteration)
    assert any(p.category == "timeout" for p in patterns)


def test_record_extracts_missing_import_pattern(memory):
    iteration = SimpleNamespace(
        index=3,
        test_output="tests/test_foo.py: missing imports for modules used in tests: re, json. Add the missing import(s) before running pytest.",
        error="",
        reflection="",
    )
    patterns = memory.record(iteration)
    assert any("re, json" in p.pattern for p in patterns)


def test_record_extracts_test_failure_pattern(memory):
    iteration = SimpleNamespace(
        index=4,
        test_output="FAILED tests/test_bar.py::test_one - AssertionError: assert 1 == 2\n1 failed in 0.01s",
        error="",
        reflection="",
    )
    patterns = memory.record(iteration)
    assert any("test_bar.py::test_one" in p.pattern for p in patterns)


def test_record_returns_empty_when_no_failures(memory):
    iteration = SimpleNamespace(
        index=5,
        test_output="1 passed in 0.01s",
        error="",
        reflection="",
    )
    assert memory.record(iteration) == []


def test_summarize_ranks_patterns(memory):
    for _ in range(3):
        memory.record(
            SimpleNamespace(
                index=1,
                test_output="tests/test_foo.py: missing imports for modules used in tests: re.",
                error="",
                reflection="",
            )
        )
    memory.record(
        SimpleNamespace(
            index=2,
            test_output="",
            error="Iteration timed out after 30s.",
            reflection="",
        )
    )
    summary = memory.summarize(limit=2)
    lines = summary.splitlines()
    assert "missing imports" in lines[0]
    assert "x3" in lines[0]
    assert "timed out" in lines[1]
    assert "x1" in lines[1]


def test_clear_drops_all_patterns(memory):
    memory.record(
        SimpleNamespace(
            index=1,
            test_output="tests/test_foo.py: missing imports for modules used in tests: re.",
            error="",
            reflection="",
        )
    )
    assert memory.summarize()
    memory.clear()
    assert memory.summarize() == ""


def test_persistence_roundtrip(tmp_path):
    memory = ErrorMemory(tmp_path)
    iteration = SimpleNamespace(
        index=1,
        test_output="tests/test_foo.py: missing imports for modules used in tests: re.",
        error="",
        reflection="",
    )
    memory.record(iteration)

    memory2 = ErrorMemory(tmp_path)
    assert "missing imports" in memory2.summarize()


def test_max_stored_cap(tmp_path):
    memory = ErrorMemory(tmp_path, max_stored=2)
    for i in range(5):
        memory.record(
            SimpleNamespace(
                index=i,
                test_output=f"FAILED tests/test_{i}.py::test_one",
                error="",
                reflection="",
            )
        )
    entries = memory._load()
    assert len(entries) == 2
