"""Tests for ALM Gate G5 (test integrity) and Gate G6 (symbol-graph under-edit).

ALM module_03. Seven tests, each closes a specific failure mode:

- ``test_net_new_pytest_skip_hard_blocks`` — an AST diff inserting a
  net-new ``pytest.skip`` call rolls back at the pre-commit gate.
- ``test_assertion_removal_inside_existing_test_hard_blocks`` — a
  diff that deletes an ``assert`` inside an existing test rolls back.
- ``test_grader_file_edit_hard_blocks`` — a diff editing
  ``tests/conftest.py::grader_helper`` rolls back on the denied-file
  glob.
- ``test_operator_handshake_permits_denied_pattern`` — a signed
  operator handshake permits an otherwise-denied ``pytest.skip``.
- ``test_under_edit_uncovered_caller_rolls_back`` — a rename where a
  call site in a sibling file still references the old name rolls
  back with ``kind="under_edit_uncovered_callers"``.
- ``test_under_edit_covered_by_test_passes`` — same rename but the
  caller is a test that still passes → no rollback.
- ``test_under_edit_explicit_declaration_passes`` — the caller is
  declared unaffected → no rollback.

Additional guards for the Second Pass adversarial questions and the
DoD leaves land at the tail:

- ``test_metaprogramming_getattr_escape_detected`` — Second Pass
  Q1 (metaprogramming AST-denial escape).
- ``test_symgraph_db_persisted_on_disk`` — DoD depth-4 leaf (c).
- ``test_manifest_validator_rejects_narrowed_test_integrity`` — DoD
  bullet on ManifestValidator.
- ``test_generated_file_excluded_from_closure`` — lateral chain
  branch C.
- ``test_platform_skip_is_exempt`` — lateral chain branch A.
- ``test_unsupported_language_emits_advisory`` — lateral chain
  branch D.
"""

from __future__ import annotations

import json
from pathlib import Path

from ract.antilazy.pre_commit import (
    TestIntegrityGateOutcome,
    UnderEditGateOutcome,
    enforce_g5,
    enforce_g6,
)
from ract.antilazy.symgraph import (
    SymbolGraph,
    build_graph,
    compute_closure,
    load_graph,
)
from ract.antilazy.testintegrity import (
    PATTERN_METAPROG_ESCAPE,
    PATTERN_PYTEST_SKIP,
    analyze_diff_python,
)
from ract.core.loop import WorkspaceSnapshot
from ract.core.transaction import ResourceBudget, StepTransaction, new_step_id
from ract.security.manifest import (
    CapabilityManifest,
    ManifestValidator,
    TestIntegrityConfig,
    default_test_integrity_config,
)
from ract.trace.sink import clear_writer, set_writer
from ract.trace.writer import JsonlEventWriter


# ---------------------------------------------------------------------------
# Helpers
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
    if not events_path.exists():
        return []
    return [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
    ]


# ---------------------------------------------------------------------------
# 1. Net-new pytest.skip hard-blocks
# ---------------------------------------------------------------------------


def test_net_new_pytest_skip_hard_blocks(tmp_path: Path) -> None:
    parent_source = (
        "import pytest\n\ndef test_divide_by_zero():\n    assert 1 / 0.0001 > 0\n"
    )
    child_source = (
        "import pytest\n"
        "\n"
        "def test_divide_by_zero():\n"
        "    pytest.skip('todo')\n"
        "    assert 1 / 0.0001 > 0\n"
    )
    parent = WorkspaceSnapshot(files={"tests/test_calc.py": parent_source})
    child = WorkspaceSnapshot(files={"tests/test_calc.py": child_source})
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("aa" * 16))
    set_writer(writer)
    try:
        outcome: TestIntegrityGateOutcome = enforce_g5(txn, parent, child)
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    patterns = {v.pattern for v in outcome.report.violations}
    assert PATTERN_PYTEST_SKIP in patterns
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    payload = laziness[0]["payload"]
    assert payload["kind"] == "test_hack_denied"
    assert PATTERN_PYTEST_SKIP in payload["patterns"]


# ---------------------------------------------------------------------------
# 2. Assertion removal inside an existing test hard-blocks
# ---------------------------------------------------------------------------


def test_assertion_removal_inside_existing_test_hard_blocks(tmp_path: Path) -> None:
    parent_source = "def test_add():\n    assert 1 + 1 == 2\n    assert 2 + 2 == 4\n"
    child_source = "def test_add():\n    assert 1 + 1 == 2\n"
    parent = WorkspaceSnapshot(files={"tests/test_add.py": parent_source})
    child = WorkspaceSnapshot(files={"tests/test_add.py": child_source})
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("bb" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g5(txn, parent, child)
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    patterns = {v.pattern for v in outcome.report.violations}
    assert "assertion_removal" in patterns
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    assert laziness[0]["payload"]["kind"] == "test_hack_denied"


# ---------------------------------------------------------------------------
# 3. Grader-file edit hard-blocks (denied glob)
# ---------------------------------------------------------------------------


def test_grader_file_edit_hard_blocks(tmp_path: Path) -> None:
    parent_source = (
        "def grader_helper(actual, expected):\n    return actual == expected\n"
    )
    child_source = "def grader_helper(actual, expected):\n    return True  # bypass\n"
    parent = WorkspaceSnapshot(files={"tests/conftest.py": parent_source})
    child = WorkspaceSnapshot(files={"tests/conftest.py": child_source})
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("cc" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g5(txn, parent, child)
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    patterns = {v.pattern for v in outcome.report.violations}
    assert "denied_file_edit" in patterns


# ---------------------------------------------------------------------------
# 4. Operator handshake permits an otherwise-denied pytest.skip
# ---------------------------------------------------------------------------


def test_operator_handshake_permits_denied_pattern(tmp_path: Path) -> None:
    parent_source = "def test_x():\n    assert True\n"
    child_source = (
        "import pytest\n"
        "\n"
        "def test_x():\n"
        "    pytest.skip('operator-approved')\n"
        "    assert True\n"
    )
    parent = WorkspaceSnapshot(files={"tests/test_x.py": parent_source})
    child = WorkspaceSnapshot(files={"tests/test_x.py": child_source})
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("dd" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g5(txn, parent, child, handshake_approved=True)
    finally:
        clear_writer()
    assert outcome.passed
    assert not outcome.should_roll_back
    # The report still records the violation for the trace; the
    # handshake_approved flag flips ``passed`` at the gate boundary.
    patterns = {v.pattern for v in outcome.report.violations}
    assert PATTERN_PYTEST_SKIP in patterns
    events = _load_events(events_path)
    # A handshake-covered denied pattern MUST emit the handshake pair
    # AND land in the advisory trace; laziness.violated does NOT fire
    # when the gate passes.
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness == [], (
        "handshake-covered denied pattern must not emit laziness.violated"
    )


# ---------------------------------------------------------------------------
# G6 helpers — small graphs built from in-memory workspaces
# ---------------------------------------------------------------------------


def _rename_graph() -> tuple[SymbolGraph, WorkspaceSnapshot]:
    """Build a graph over a two-file workspace where ``report`` calls
    ``billing.total`` — the pre-rename baseline.
    """
    workspace = WorkspaceSnapshot(
        files={
            "src/billing.py": ("def total(items):\n    return sum(items)\n"),
            "src/report.py": (
                "from src.billing import total\n"
                "\n"
                "def build_summary(items):\n"
                "    return f'total = {total(items)}'\n"
            ),
        }
    )
    graph = build_graph(workspace)
    return graph, workspace


# ---------------------------------------------------------------------------
# 5. Under-edit — uncovered caller rolls back
# ---------------------------------------------------------------------------


def test_under_edit_uncovered_caller_rolls_back(tmp_path: Path) -> None:
    graph, _ = _rename_graph()
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("ee" * 16))
    set_writer(writer)
    try:
        outcome: UnderEditGateOutcome = enforce_g6(
            txn,
            graph,
            edited_symbols=("src.billing.total",),
            edited_files=("src/billing.py",),
            passing_tests_touched=(),
            declared_unaffected=(),
        )
    finally:
        clear_writer()
    assert not outcome.passed
    assert outcome.should_roll_back
    assert "src.report.build_summary" in outcome.report.uncovered
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness
    payload = laziness[0]["payload"]
    assert payload["kind"] == "under_edit_uncovered_callers"
    assert "src.report.build_summary" in payload["uncovered"]


# ---------------------------------------------------------------------------
# 6. Under-edit — covered by a passing test → no rollback
# ---------------------------------------------------------------------------


def test_under_edit_covered_by_test_passes(tmp_path: Path) -> None:
    graph, _ = _rename_graph()
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("11" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g6(
            txn,
            graph,
            edited_symbols=("src.billing.total",),
            edited_files=("src/billing.py",),
            passing_tests_touched=("src.report.build_summary",),
        )
    finally:
        clear_writer()
    assert outcome.passed
    assert not outcome.should_roll_back
    assert "src.report.build_summary" in outcome.report.covered_by_test
    events = _load_events(events_path)
    laziness = [e for e in events if e["kind"] == "laziness.violated"]
    assert laziness == []


# ---------------------------------------------------------------------------
# 7. Under-edit — explicit declaration of unaffectedness → no rollback
# ---------------------------------------------------------------------------


def test_under_edit_explicit_declaration_passes(tmp_path: Path) -> None:
    graph, _ = _rename_graph()
    txn = _make_transaction(tmp_path)
    events_path = tmp_path / "events.jsonl"
    writer = JsonlEventWriter(path=events_path, run_id=bytes.fromhex("22" * 16))
    set_writer(writer)
    try:
        outcome = enforce_g6(
            txn,
            graph,
            edited_symbols=("src.billing.total",),
            edited_files=("src/billing.py",),
            declared_unaffected=("src.report.build_summary",),
        )
    finally:
        clear_writer()
    assert outcome.passed
    assert not outcome.should_roll_back
    assert "src.report.build_summary" in outcome.report.covered_by_declaration


# ---------------------------------------------------------------------------
# 8. Second Pass Q1 — metaprogramming escape detection
# ---------------------------------------------------------------------------


def test_metaprogramming_getattr_escape_detected() -> None:
    """A child that constructs ``pytest.skip`` via ``getattr`` must be caught.

    Second Pass adversarial question 1: the literal-AST analyzer would
    miss ``getattr(pytest, 'skip')()``; the escape detector surfaces
    the shape under ``test_integrity_metaprogramming_escape``.
    """
    parent_source = "def test_smoke():\n    assert True\n"
    child_source = (
        "import pytest\n"
        "\n"
        "def test_smoke():\n"
        "    getattr(pytest, 'skip')('metaprogramming bypass')\n"
        "    assert True\n"
    )
    violations = analyze_diff_python(
        "tests/test_smoke.py",
        parent_source,
        child_source,
        default_test_integrity_config(),
    )
    patterns = {v.pattern for v in violations}
    assert PATTERN_METAPROG_ESCAPE in patterns, (
        f"expected metaprogramming escape detection; got patterns={patterns}"
    )


# ---------------------------------------------------------------------------
# 8b. Second Pass Cycle-2 fix — importlib.import_module escape detected
# ---------------------------------------------------------------------------


def test_importlib_import_module_escape_detected() -> None:
    """Second Pass Cycle-2 fix for adversarial Q1.

    The reviewer named ``importlib.import_module('pytest').skip()`` as a
    metaprogramming shape the original escape detector missed. The
    Cycle-2 fix extends ``_detect_metaprogramming_escape`` to catch
    the ``Attribute(Call(importlib.import_module, "pytest"), "skip")``
    shape.
    """
    parent_source = "def test_smoke():\n    assert True\n"
    child_source = (
        "import importlib\n"
        "\n"
        "def test_smoke():\n"
        "    importlib.import_module('pytest').skip('bypass')\n"
        "    assert True\n"
    )
    violations = analyze_diff_python(
        "tests/test_smoke.py",
        parent_source,
        child_source,
        default_test_integrity_config(),
    )
    patterns = {v.pattern for v in violations}
    assert PATTERN_METAPROG_ESCAPE in patterns, (
        f"expected importlib escape detection; got {patterns}"
    )


# ---------------------------------------------------------------------------
# 8c. Second Pass Cycle-2 fix — type().__getattribute__ escape detected
# ---------------------------------------------------------------------------


def test_type_getattribute_escape_detected() -> None:
    """Second Pass Cycle-2 fix for adversarial Q1.

    ``type(pytest).__getattribute__(pytest, 'skip')()`` is a class-
    attribute lookup shape that reaches the same denied target. The
    Cycle-2 fix in ``_detect_metaprogramming_escape`` names it under
    ``PATTERN_METAPROG_ESCAPE``.
    """
    parent_source = "def test_smoke():\n    assert True\n"
    child_source = (
        "import pytest\n"
        "\n"
        "def test_smoke():\n"
        "    type(pytest).__getattribute__(pytest, 'skip')('bypass')\n"
        "    assert True\n"
    )
    violations = analyze_diff_python(
        "tests/test_smoke.py",
        parent_source,
        child_source,
        default_test_integrity_config(),
    )
    patterns = {v.pattern for v in violations}
    assert PATTERN_METAPROG_ESCAPE in patterns, (
        f"expected type().__getattribute__ escape detection; got {patterns}"
    )


# ---------------------------------------------------------------------------
# 9. DoD leaf (c) — symgraph.db persisted on disk after loop entry
# ---------------------------------------------------------------------------


def test_symgraph_db_persisted_on_disk(tmp_path: Path) -> None:
    workspace = WorkspaceSnapshot(
        files={
            "src/a.py": "def foo():\n    return 1\n",
            "src/b.py": ("from src.a import foo\ndef bar():\n    return foo()\n"),
        }
    )
    db_path = tmp_path / "symgraph.db"
    graph = build_graph(workspace, cache_db=db_path)
    assert db_path.exists(), "symgraph.db must be persisted after loop entry"
    # symbols table populated with parsed Python symbols
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        row_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    finally:
        conn.close()
    assert row_count == len(graph.symbols)
    assert row_count >= 2  # foo + bar

    # Re-loading returns the same graph without re-parsing
    reloaded = load_graph(db_path, graph.snapshot_digest)
    assert reloaded is not None
    assert set(reloaded.symbols.keys()) == set(graph.symbols.keys())


# ---------------------------------------------------------------------------
# 10. DoD bullet — ManifestValidator rejects narrowed test_integrity
# ---------------------------------------------------------------------------


def test_manifest_validator_rejects_narrowed_test_integrity() -> None:
    narrowed = TestIntegrityConfig(denied_ast_patterns=())
    manifest = CapabilityManifest(
        run_id="test-run",
        test_integrity=narrowed,
    )
    violations = ManifestValidator.validate(manifest)
    codes = {v.code for v in violations}
    assert "test_integrity_section_narrowed" in codes, (
        f"validator must refuse an empty denied_ast_patterns; got {codes}"
    )


# ---------------------------------------------------------------------------
# 11. Lateral branch C — generated files are excluded from the closure
# ---------------------------------------------------------------------------


def test_generated_file_excluded_from_closure() -> None:
    # ``report.py`` is annotated linguist-generated=true via
    # .gitattributes; the closure over ``billing.total`` must not
    # surface build_summary as uncovered because a generator ships a
    # new version separately.
    workspace = WorkspaceSnapshot(
        files={
            ".gitattributes": ("src/report.py linguist-generated=true\n"),
            "src/billing.py": "def total(items):\n    return sum(items)\n",
            "src/report.py": (
                "from src.billing import total\n"
                "def build_summary(items):\n"
                "    return total(items)\n"
            ),
        }
    )
    graph = build_graph(workspace)
    report = compute_closure(
        graph,
        edited_symbols=("src.billing.total",),
        edited_files=("src/billing.py",),
    )
    # ``report.py`` is excluded → build_summary neither uncovered nor
    # downstream. The generated_excluded field carries it if it was
    # in the initial downstream set.
    assert "src.report.build_summary" not in report.uncovered


# ---------------------------------------------------------------------------
# 12. Lateral branch A — pytest.skip with sys.platform is exempt
# ---------------------------------------------------------------------------


def test_platform_skip_is_exempt() -> None:
    parent_source = "def test_x():\n    assert True\n"
    child_source = (
        "import sys\n"
        "import pytest\n"
        "\n"
        "def test_x():\n"
        "    if sys.platform == 'linux':\n"
        "        pytest.skip('requires windows')\n"
        "    assert True\n"
    )
    violations = analyze_diff_python(
        "tests/test_x.py",
        parent_source,
        child_source,
        default_test_integrity_config(),
    )
    patterns = {v.pattern for v in violations}
    assert PATTERN_PYTEST_SKIP not in patterns, (
        "portability skip with a platform reason must be exempt"
    )


# ---------------------------------------------------------------------------
# 13. Lateral branch D — unsupported language emits an advisory
# ---------------------------------------------------------------------------


def test_unsupported_language_emits_advisory(tmp_path: Path) -> None:
    parent = WorkspaceSnapshot(files={"tests/foo.test.ts": "export const x = 1;\n"})
    child = WorkspaceSnapshot(files={"tests/foo.test.ts": "export const x = 2;\n"})
    txn = _make_transaction(tmp_path)
    outcome = enforce_g5(txn, parent, child)
    advisory = outcome.report.advisory_violations()
    patterns = {v.pattern for v in advisory}
    assert "test_integrity_unsupported_language" in patterns
    assert outcome.passed, "advisory alone must not fail the gate"


# RACT 0.4.0
