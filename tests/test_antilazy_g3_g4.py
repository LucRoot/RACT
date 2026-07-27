"""Tests for ALM Gate G3 (patch differentiation) and Gate G4 (coverage delta).

ALM module_02. Seven tests, each closes a specific failure mode:

- ``test_semantic_noop_rolls_back`` — zero surviving differentiators
  against the null baseline rolls back and emits
  ``laziness.violated`` with ``kind="semantic_noop"``.
- ``test_solution_leakage_rolls_back`` — a hunk whose bytes match a
  prior commit rolls back with ``kind="solution_leakage"``.
- ``test_coverage_ratio_below_tau_rolls_back`` — coverage_ratio 0.4
  under tau_cov 0.8 rolls back with
  ``kind="coverage_delta_insufficient"``.
- ``test_mutation_coverage_delta_below_delta_mut_rolls_back`` — a
  non-trivial change with mutation delta 0 rolls back.
- ``test_trivial_change_bypasses_mutation_delta`` — a formatter-only
  diff is classified trivial and the mutation-delta check is skipped.
- ``test_flaky_differentiator_filtered`` — a companion test whose
  outcome differs across three runs is dropped.
- ``test_worked_example_null_patch_visible_passes_g3_catches`` — a
  fixture whose visible suite is green on the null patch triggers
  G3's semantic-noop path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ract.antilazy.coverage import _classify_triviality
from ract.antilazy.mutation import MutationReport
from ract.antilazy.patchdiff import (
    GeneratedTest,
    Hunk,
    Patch,
    PatchDifferentiationReport,
    generate_differentiators,
    null_patch,
    run_patchdiff,
)
from ract.antilazy.pre_commit import (
    CoverageDeltaGateOutcome,
    PatchDiffGateOutcome,
    enforce_g3,
    enforce_g4,
)
from ract.core.loop import WorkspaceSnapshot
from ract.core.transaction import ResourceBudget, StepTransaction, new_step_id
from ract.trace.sink import clear_writer, set_writer
from ract.trace.writer import JsonlEventWriter


# ---------------------------------------------------------------------------
# Test doubles — generators, runners, retrieval indexes
# ---------------------------------------------------------------------------


class _EmptyGenerator:
    """Returns no differentiators for any function."""

    def generate(
        self, patch: Patch, baseline: Patch, target_function: str, max_tests: int
    ) -> tuple[GeneratedTest, ...]:
        return ()


class _AlwaysSameRunner:
    """Runner whose verdict is identical for every test / patch pair.

    Simulates a semantic-noop scenario: no test can distinguish the
    patch from the baseline.
    """

    def run(self, test: GeneratedTest, patch: Patch) -> bool:
        return True


@dataclass
class _DeterministicGenerator:
    """Generator that emits one distinguishing test per touched function."""

    ids_by_function: dict[str, str] = field(default_factory=dict)

    def generate(
        self, patch: Patch, baseline: Patch, target_function: str, max_tests: int
    ) -> tuple[GeneratedTest, ...]:
        if max_tests <= 0:
            return ()
        tid = self.ids_by_function.get(target_function, f"gen_{target_function}")
        return (
            GeneratedTest(
                id=tid,
                source=f"def test_{tid}(): pass",
                target_function=target_function,
            ),
        )


@dataclass
class _DifferentiatingRunner:
    """Runner that returns True on the patch and False on the baseline.

    Every test in the fixture set thereby distinguishes patch from
    baseline; the flakiness check passes (three identical runs).
    """

    patch_digest: str

    def run(self, test: GeneratedTest, patch: Patch) -> bool:
        return patch.digest() == self.patch_digest


@dataclass
class _FlakyRunner:
    """Runner whose verdict cycles per-call so the flakiness filter fires."""

    _counter: int = 0

    def run(self, test: GeneratedTest, patch: Patch) -> bool:  # noqa: ARG002
        self._counter += 1
        return self._counter % 2 == 0


class _EmptyRetrievalIndex:
    def contains_hunk(self, hunk: Hunk) -> tuple[str, ...]:
        return ()


@dataclass
class _MatchingRetrievalIndex:
    """RetrievalIndex that returns fixed refs for any qualifying hunk."""

    refs: tuple[str, ...] = ("ref-leakage-01",)

    def contains_hunk(self, hunk: Hunk) -> tuple[str, ...]:
        return self.refs


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------


def _make_transaction(tmp_path: Path) -> StepTransaction:
    return StepTransaction(
        step_id=new_step_id(),
        parent_snapshot="deadbeef",
        worktree_path=tmp_path / "wt",
        postconditions=(),
        timeout_seconds=60,
        budget=ResourceBudget(),
    )


def _load_events(events_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]


# ---------------------------------------------------------------------------
# 1. Semantic no-op rolls back
# ---------------------------------------------------------------------------


def test_semantic_noop_rolls_back(tmp_path: Path) -> None:
    # A patch whose only added line is a redundant `pass` inside a
    # touched function. The generator refuses to produce
    # differentiators (empty generator) so ``tests_that_distinguish``
    # stays 0 and G3 marks the patch is_semantic_noop.
    patch = Patch(
        hunks=(
            Hunk(
                path="src/calc.py",
                added_lines=(
                    "def mul(a, b):",
                    "    return a * b",
                ),
                removed_lines=(
                    "def mul(a, b):",
                    "    return a * b",
                ),
            ),
        )
    )
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("aa" * 16))
    set_writer(writer)
    try:
        outcome: PatchDiffGateOutcome = enforce_g3(
            txn,
            patch,
            tmp_path,
            generator=_EmptyGenerator(),
            runner=_AlwaysSameRunner(),
            baseline_kind="null",
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert outcome.report.is_semantic_noop
    assert outcome.report.tests_that_distinguish == 0
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    assert laziness[0]["payload"]["kind"] == "semantic_noop"


# ---------------------------------------------------------------------------
# 2. Solution leakage rolls back — retrieval-index adapter provides the match
# ---------------------------------------------------------------------------


def test_solution_leakage_rolls_back(tmp_path: Path) -> None:
    # A hunk with 6 lines / 200+ chars clears the leakage floor. The
    # matching retrieval index returns a ref; G3 must roll back and
    # emit ``solution_leakage``.
    payload_lines = tuple(
        f"    line_{i} = {i}  # padding to clear the 100-char floor"
        for i in range(6)
    )
    patch = Patch(
        hunks=(
            Hunk(
                path="src/dates.py",
                added_lines=payload_lines,
                removed_lines=(),
            ),
        )
    )
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("bb" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g3(
            txn,
            patch,
            tmp_path,
            generator=_EmptyGenerator(),
            runner=_AlwaysSameRunner(),
            retrieval_index=_MatchingRetrievalIndex(refs=("git:abc123",)),
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert outcome.report.leakage_matches == ("git:abc123",)
    assert outcome.report.baseline_kind == "commit_leak"
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    payload = laziness[0]["payload"]
    assert payload["kind"] == "solution_leakage"
    assert "git:abc123" in payload["leakage_matches"]


# ---------------------------------------------------------------------------
# 3. Coverage ratio below tau rolls back
# ---------------------------------------------------------------------------


def _mutation_report(kill_rate: float) -> MutationReport:
    return MutationReport(
        touched_files=("src/x.py",),
        mutants_total=10,
        mutants_killed=int(kill_rate * 10),
        mutants_survived=(),
        mutants_equivalent=(),
        kill_rate=kill_rate,
        threshold=0.7,
    )


def test_coverage_ratio_below_tau_rolls_back(tmp_path: Path) -> None:
    # Ten added lines; only four are marked covered → ratio 0.4 < 0.8.
    added = tuple(f"    x{i} = {i}" for i in range(10))
    patch = Patch(
        hunks=(
            Hunk(
                path="src/x.py",
                added_lines=added,
                removed_lines=(),
            ),
        )
    )
    parent = WorkspaceSnapshot(files={"src/x.py": ""})
    child = WorkspaceSnapshot(
        files={"src/x.py": "\n".join(added)},
        metadata={"coverage.src/x.py": [1, 2, 3, 4]},
    )
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("cc" * 16))
    set_writer(writer)
    try:
        outcome: CoverageDeltaGateOutcome = enforce_g4(
            txn,
            patch,
            parent,
            child,
            mutation_report_parent=_mutation_report(0.8),
            mutation_report_child=_mutation_report(0.8),
            tau_cov=0.8,
            delta_mut=0.1,
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert outcome.report.coverage_ratio == pytest.approx(0.4)
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    assert laziness[0]["payload"]["kind"] == "coverage_delta_insufficient"


# ---------------------------------------------------------------------------
# 4. Mutation coverage delta below delta_mut rolls back
# ---------------------------------------------------------------------------


def test_mutation_coverage_delta_below_delta_mut_rolls_back(tmp_path: Path) -> None:
    # A non-trivial change with the same mutation kill rate on parent
    # and child → mutation_coverage_delta = 0 < 0.1. Also make coverage
    # pass so the failure is unambiguously the mutation-delta one.
    added = tuple(f"    v{i} = {i}" for i in range(10))
    patch = Patch(
        hunks=(
            Hunk(
                path="src/y.py",
                added_lines=added,
                removed_lines=(),
            ),
        )
    )
    parent = WorkspaceSnapshot(files={"src/y.py": ""})
    child = WorkspaceSnapshot(
        files={"src/y.py": "\n".join(added)},
        metadata={"coverage.src/y.py": list(range(1, 11))},
    )
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("dd" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g4(
            txn,
            patch,
            parent,
            child,
            mutation_report_parent=_mutation_report(0.8),
            mutation_report_child=_mutation_report(0.8),
            tau_cov=0.8,
            delta_mut=0.1,
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert outcome.report.coverage_ratio == pytest.approx(1.0)
    assert outcome.report.mutation_coverage_delta == pytest.approx(0.0)
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    assert laziness[0]["payload"]["kind"] == "coverage_delta_insufficient"


# ---------------------------------------------------------------------------
# 5. Trivial change bypasses mutation-delta check
# ---------------------------------------------------------------------------


def test_trivial_change_bypasses_mutation_delta(tmp_path: Path) -> None:
    # A one-line whitespace reflow: added / removed differ only in
    # trailing whitespace. `_classify_triviality` returns True; the
    # mutation-delta check is skipped even though the delta is 0.
    added = ("    x = 1",)  # trailing space stripped
    removed = ("    x = 1  ",)  # trailing whitespace
    assert _classify_triviality(added, removed) is True
    patch = Patch(
        hunks=(
            Hunk(
                path="src/z.py",
                added_lines=added,
                removed_lines=removed,
            ),
        )
    )
    parent = WorkspaceSnapshot(files={"src/z.py": "    x = 1  "})
    child = WorkspaceSnapshot(
        files={"src/z.py": "    x = 1"},
        metadata={"coverage.src/z.py": [1]},
    )
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("ee" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g4(
            txn,
            patch,
            parent,
            child,
            mutation_report_parent=_mutation_report(0.5),
            mutation_report_child=_mutation_report(0.5),
            tau_cov=0.8,
            delta_mut=0.1,
        )
    finally:
        clear_writer()
    assert outcome.passed
    assert not outcome.should_roll_back
    assert outcome.report.is_trivial_change is True
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness == []


# ---------------------------------------------------------------------------
# 6. Flaky differentiator is filtered
# ---------------------------------------------------------------------------


def test_flaky_differentiator_filtered() -> None:
    patch = Patch(
        hunks=(
            Hunk(
                path="src/calc.py",
                added_lines=("def double(x):", "    return x + x"),
                removed_lines=(),
            ),
        )
    )
    baseline = null_patch()
    kept = generate_differentiators(
        patch,
        baseline,
        _DeterministicGenerator(),
        _FlakyRunner(),
        total_budget=5,
        per_function_cap=5,
        flakiness_runs=3,
    )
    # The flaky runner alternates, so no candidate survives the three-
    # run flakiness filter → kept is empty.
    assert kept == ()


# ---------------------------------------------------------------------------
# 7. Worked example — null patch visible passes, G3 catches
# ---------------------------------------------------------------------------


def test_worked_example_null_patch_visible_passes_g3_catches(tmp_path: Path) -> None:
    """Fixture-shaped: the visible test suite is green on the null patch
    (both ``test_add_ok`` and ``test_mul_ok`` already pass), so
    substrate T1 cannot see the failure. G3 surfaces it because no
    differentiator survives against the null baseline.
    """
    fixture_root = (
        Path(__file__).resolve().parent.parent
        / "evals"
        / "antilazy"
        / "G3-G4"
        / "null_patch"
    )
    assert fixture_root.exists(), "null_patch fixture must ship"
    expected = json.loads((fixture_root / "expected.json").read_text(encoding="utf-8"))
    assert expected["is_semantic_noop_expected"] is True

    # The "claimed patch" is a rewrite of `mul` that matches the pre-
    # existing behaviour byte-for-byte. Empty generator → zero
    # differentiators → G3 marks it a no-op.
    patch = Patch(
        hunks=(
            Hunk(
                path="src/calc.py",
                added_lines=(
                    "def mul(a, b):",
                    "    return a * b",
                ),
                removed_lines=(
                    "def mul(a, b):",
                    "    return a * b",
                ),
            ),
        )
    )
    report: PatchDifferentiationReport = run_patchdiff(
        patch,
        tmp_path,
        generator=_EmptyGenerator(),
        runner=_AlwaysSameRunner(),
        baseline_kind="null",
    )
    assert report.is_semantic_noop is True
    assert report.tests_that_distinguish == 0
    assert report.leakage_matches == ()


# RACT 0.4.0
