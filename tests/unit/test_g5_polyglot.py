"""Regression tests for the polyglot G5 dead-code gate (module_08)."""

from __future__ import annotations

from pathlib import Path


from ract.antilazy.dead_code_polyglot import (
    DeadCodePolyglotReport,
    scan_dead_code,
    scan_dead_code_in_dir,
)
from ract.antilazy.pre_commit import (
    enforce_g5_dead_code_polyglot,
)


# ---------------------------------------------------------------------------
# Per-language: dead code detected
# ---------------------------------------------------------------------------


def test_python_unreferenced_function_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text(
        "def used():\n    return 1\ndef orphan():\n    return 2\nprint(used())\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "orphan" in idents
    assert "used" not in idents


def test_javascript_unreferenced_function_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.js"
    p.write_text(
        "function used(x) { return x; }\n"
        "function orphan(x) { return x + 1; }\n"
        "console.log(used(1));\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "orphan" in idents
    assert "used" not in idents


def test_typescript_unreferenced_type_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.ts"
    p.write_text(
        "type UsedType = string;\n"
        "type OrphanType = number;\n"
        "const x: UsedType = 'a';\n"
        "console.log(x);\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "OrphanType" in idents
    assert "UsedType" not in idents


def test_rust_unreferenced_function_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.rs"
    p.write_text(
        "fn used() -> i32 { 1 }\n"
        "fn orphan() -> i32 { 2 }\n"
        'fn main() { println!("{}", used()); }\n'
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "orphan" in idents
    assert "used" not in idents


def test_go_unreferenced_type_flagged(tmp_path: Path) -> None:
    p = tmp_path / "m.go"
    p.write_text(
        "package main\n"
        "type Used struct{ X int }\n"
        "type Orphan struct{ Y int }\n"
        "func main() { _ = Used{X: 1} }\n"
    )
    report = scan_dead_code([p])
    idents = {c.identifier for c in report.candidates}
    assert "Orphan" in idents
    assert "Used" not in idents


# ---------------------------------------------------------------------------
# Referenced identifiers NOT flagged
# ---------------------------------------------------------------------------


def test_cross_file_reference_suppresses_candidate(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("def util():\n    return 1\n")
    b.write_text("from a import util\nprint(util())\n")
    report = scan_dead_code([a, b])
    idents = {c.identifier for c in report.candidates}
    assert "util" not in idents


def test_ignore_leading_underscore_default(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def _private():\n    return 1\n")
    report = scan_dead_code([p])
    assert not any(c.identifier == "_private" for c in report.candidates)


def test_ignore_leading_underscore_disabled(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def _private():\n    return 1\n")
    report = scan_dead_code([p], ignore_leading_underscore=False)
    assert any(c.identifier == "_private" for c in report.candidates)


def test_default_ignore_names_suppresses_main(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def main():\n    return 0\n")
    report = scan_dead_code([p])
    assert not any(c.identifier == "main" for c in report.candidates)


# ---------------------------------------------------------------------------
# Unsupported / skip behaviour
# ---------------------------------------------------------------------------


def test_unsupported_extension_skipped(tmp_path: Path) -> None:
    p = tmp_path / "README.md"
    p.write_text("# hi\n")
    report = scan_dead_code([p])
    assert str(p) in report.skipped_files
    assert report.candidates == ()


def test_scan_in_dir_ignores_vendor_dirs(tmp_path: Path) -> None:
    ok = tmp_path / "m.py"
    vendor = tmp_path / "node_modules" / "m.py"
    vendor.parent.mkdir()
    ok.write_text("def a():\n    return 1\n")
    vendor.write_text("def vendored_orphan():\n    return 2\n")
    report = scan_dead_code_in_dir(tmp_path)
    assert not any(c.identifier == "vendored_orphan" for c in report.candidates)


# ---------------------------------------------------------------------------
# Python parity: pre- vs post-module_08 on Python-only file
# ---------------------------------------------------------------------------


def test_python_parity_ast_versus_polyglot(tmp_path: Path) -> None:
    """The polyglot Python path IS the pre-module_08 AST path.

    A workspace containing only Python files must produce a report
    whose candidate set contains all functions/classes/constants NOT
    referenced anywhere. That contract does not depend on tree-sitter
    at all -- Python routes through :mod:`ast`. This test locks the
    behaviour so a future refactor of the shared walker cannot silently
    diverge Python from its historical AST result.
    """
    p = tmp_path / "workspace.py"
    p.write_text(
        "def a():\n"
        "    return 1\n"
        "def b():\n"
        "    return 2\n"
        "def c():\n"
        "    return 3\n"
        "print(a())\n"
        "print(c())\n"
    )
    report = scan_dead_code([p])
    idents = sorted(c.identifier for c in report.candidates)
    assert idents == ["b"]


# ---------------------------------------------------------------------------
# Gate outcome shim
# ---------------------------------------------------------------------------


def test_gate_outcome_pass_on_clean_repo(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def a():\n    return 1\nprint(a())\n")
    outcome = enforce_g5_dead_code_polyglot([p])
    assert outcome.passed is True
    assert outcome.should_roll_back is False


def test_gate_outcome_fail_on_dead_code(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def orphan():\n    return 1\n")
    outcome = enforce_g5_dead_code_polyglot([p])
    assert outcome.passed is False
    assert outcome.should_roll_back is True


def test_gate_outcome_threshold(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def orphan():\n    return 1\n")
    outcome = enforce_g5_dead_code_polyglot([p], threshold=1)
    assert outcome.passed is True


def test_report_passed_helper() -> None:
    from ract.antilazy.dead_code_polyglot import DeadCodeCandidate

    r_empty = DeadCodePolyglotReport()
    assert r_empty.passed() is True
    r_one = DeadCodePolyglotReport(
        candidates=(
            DeadCodeCandidate(
                file="a",
                language="python",
                identifier="x",
                kind="function",
                start_row=0,
                start_col=0,
            ),
        )
    )
    assert r_one.passed() is False
    assert r_one.passed(threshold=1) is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_file_no_candidates(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("")
    report = scan_dead_code([p])
    assert report.candidates == ()


def test_syntax_error_does_not_raise(tmp_path: Path) -> None:
    p = tmp_path / "m.py"
    p.write_text("def broken(:\n")
    # Must not raise; simply extracts nothing.
    scan_dead_code([p])


def test_read_failure_lands_in_skipped(tmp_path: Path) -> None:
    ghost = tmp_path / "does_not_exist.py"
    report = scan_dead_code([ghost])
    assert str(ghost) in report.skipped_files
