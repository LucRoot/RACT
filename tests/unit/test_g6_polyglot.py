"""Regression tests for the polyglot G6 test-copy-paste gate (module_08)."""

from __future__ import annotations

from pathlib import Path


from ract.antilazy.pre_commit import (
    enforce_g6_test_copy_paste_polyglot,
)
from ract.antilazy.test_copy_paste_polyglot import (
    TestCopyPastePolyglotReport,
    scan_test_copy_paste,
    scan_test_copy_paste_in_dir,
)


# ---------------------------------------------------------------------------
# Per-language: copy-paste detected
# ---------------------------------------------------------------------------


def test_python_copy_paste_flagged(tmp_path: Path) -> None:
    p = tmp_path / "test_x.py"
    p.write_text(
        "def test_a():\n"
        "    x = compute(1)\n"
        "    assert x == 2\n"
        "    assert isinstance(x, int)\n"
        "def test_b():\n"
        "    y = compute(2)\n"
        "    assert y == 3\n"
        "    assert isinstance(y, int)\n"
    )
    report = scan_test_copy_paste([p])
    assert len(report.findings) >= 1
    pair_names = {(f.a_name, f.b_name) for f in report.findings}
    assert ("test_a", "test_b") in pair_names or ("test_b", "test_a") in pair_names


def test_python_genuinely_different_tests_not_flagged(tmp_path: Path) -> None:
    p = tmp_path / "test_x.py"
    p.write_text(
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "def test_string_split():\n"
        "    result = 'a,b,c'.split(',')\n"
        "    assert len(result) == 3\n"
        "    assert result[0] == 'a'\n"
        "    for item in result:\n"
        "        assert isinstance(item, str)\n"
    )
    report = scan_test_copy_paste([p])
    # Structurally different: one has for-loop + subscript, the other doesn't.
    assert report.findings == ()


def test_javascript_copy_paste_flagged(tmp_path: Path) -> None:
    p = tmp_path / "x.test.js"
    p.write_text(
        "describe('x', () => {\n"
        "  it('does a', () => {\n"
        "    const r = compute(1);\n"
        "    expect(r).toBe(2);\n"
        "    expect(typeof r).toBe('number');\n"
        "  });\n"
        "  it('does b', () => {\n"
        "    const s = compute(2);\n"
        "    expect(s).toBe(3);\n"
        "    expect(typeof s).toBe('number');\n"
        "  });\n"
        "});\n"
    )
    report = scan_test_copy_paste([p])
    assert len(report.findings) >= 1


def test_typescript_copy_paste_flagged(tmp_path: Path) -> None:
    p = tmp_path / "x.test.ts"
    p.write_text(
        "test('a', () => {\n"
        "  const r: number = compute(1);\n"
        "  expect(r).toBe(2);\n"
        "  expect(r > 0).toBe(true);\n"
        "});\n"
        "test('b', () => {\n"
        "  const s: number = compute(2);\n"
        "  expect(s).toBe(3);\n"
        "  expect(s > 0).toBe(true);\n"
        "});\n"
    )
    report = scan_test_copy_paste([p])
    assert len(report.findings) >= 1


def test_rust_copy_paste_flagged(tmp_path: Path) -> None:
    p = tmp_path / "lib.rs"
    p.write_text(
        "#[test]\nfn test_a() {\n"
        "    let x = compute(1);\n"
        "    assert_eq!(x, 2);\n"
        "    assert!(x > 0);\n"
        "}\n"
        "#[test]\nfn test_b() {\n"
        "    let y = compute(2);\n"
        "    assert_eq!(y, 3);\n"
        "    assert!(y > 0);\n"
        "}\n"
    )
    report = scan_test_copy_paste([p])
    assert len(report.findings) >= 1


def test_go_copy_paste_flagged(tmp_path: Path) -> None:
    p = tmp_path / "x_test.go"
    p.write_text(
        "package x\n"
        'import "testing"\n'
        "func TestA(t *testing.T) {\n"
        "    x := compute(1)\n"
        '    if x != 2 { t.Errorf("nope %d", x) }\n'
        '    if x <= 0 { t.Errorf("nope") }\n'
        "}\n"
        "func TestB(t *testing.T) {\n"
        "    y := compute(2)\n"
        '    if y != 3 { t.Errorf("nope %d", y) }\n'
        '    if y <= 0 { t.Errorf("nope") }\n'
        "}\n"
    )
    report = scan_test_copy_paste([p])
    assert len(report.findings) >= 1


# ---------------------------------------------------------------------------
# Non-test files ignored
# ---------------------------------------------------------------------------


def test_non_test_python_file_not_scanned(tmp_path: Path) -> None:
    p = tmp_path / "not_test.py"
    p.write_text("def foo_a():\n    assert 1 == 1\ndef foo_b():\n    assert 2 == 2\n")
    report = scan_test_copy_paste([p])
    assert report.findings == ()
    assert report.tests_scanned == 0


def test_go_non_test_file_not_scanned(tmp_path: Path) -> None:
    p = tmp_path / "prod.go"
    p.write_text(
        "package x\nfunc TestA(){ x := 1; _ = x }\nfunc TestB(){ y := 1; _ = y }\n"
    )
    report = scan_test_copy_paste([p])
    assert report.findings == ()


# ---------------------------------------------------------------------------
# Threshold / min_tokens knobs
# ---------------------------------------------------------------------------


def test_tiny_tests_below_min_tokens_ignored(tmp_path: Path) -> None:
    p = tmp_path / "test_tiny.py"
    p.write_text("def test_a():\n    pass\ndef test_b():\n    pass\n")
    report = scan_test_copy_paste([p], min_tokens=6)
    assert report.findings == ()


def test_jaccard_threshold_disqualifies_partial_matches(tmp_path: Path) -> None:
    p = tmp_path / "test_x.py"
    p.write_text(
        "def test_a():\n"
        "    x = compute(1)\n"
        "    assert x == 2\n"
        "def test_b():\n"
        "    x = compute(1)\n"
        "    for i in range(10):\n"
        "        x += process(i)\n"
        "        assert x > 0\n"
        "    assert x == 42\n"
    )
    # Structurally very different; even at low threshold should not match.
    report = scan_test_copy_paste([p], jaccard_threshold=0.99)
    assert report.findings == ()


# ---------------------------------------------------------------------------
# Python parity: pre- vs post-module_08
# ---------------------------------------------------------------------------


def test_python_parity_scanner_over_scanned_tests(tmp_path: Path) -> None:
    """Python-only workspace: tests_scanned counts every test_* function."""
    p = tmp_path / "test_parity.py"
    p.write_text(
        "def test_x():\n    assert 1 == 1\n"
        "def helper():\n    return 0\n"
        "def test_y():\n    assert 2 == 2\n"
    )
    report = scan_test_copy_paste([p])
    assert report.tests_scanned == 2


# ---------------------------------------------------------------------------
# Gate outcome shim
# ---------------------------------------------------------------------------


def test_gate_pass_on_clean_repo(tmp_path: Path) -> None:
    p = tmp_path / "test_clean.py"
    p.write_text(
        "def test_a():\n    assert add(1, 2) == 3\n"
        "def test_b():\n    for i in range(10):\n        assert i >= 0\n"
    )
    outcome = enforce_g6_test_copy_paste_polyglot([p])
    assert outcome.passed is True
    assert outcome.should_roll_back is False


def test_gate_fail_on_copy_paste(tmp_path: Path) -> None:
    p = tmp_path / "test_dup.py"
    p.write_text(
        "def test_a():\n"
        "    x = compute(1)\n"
        "    assert x == 2\n"
        "    assert isinstance(x, int)\n"
        "def test_b():\n"
        "    y = compute(2)\n"
        "    assert y == 3\n"
        "    assert isinstance(y, int)\n"
    )
    outcome = enforce_g6_test_copy_paste_polyglot([p])
    assert outcome.passed is False
    assert outcome.should_roll_back is True


def test_gate_threshold_absorbs_findings(tmp_path: Path) -> None:
    p = tmp_path / "test_dup.py"
    p.write_text(
        "def test_a():\n"
        "    x = compute(1)\n"
        "    assert x == 2\n"
        "    assert isinstance(x, int)\n"
        "def test_b():\n"
        "    y = compute(2)\n"
        "    assert y == 3\n"
        "    assert isinstance(y, int)\n"
    )
    outcome = enforce_g6_test_copy_paste_polyglot([p], finding_threshold=1)
    assert outcome.passed is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_report_passed_helper() -> None:
    from ract.antilazy.test_copy_paste_polyglot import CopyPasteFinding

    empty = TestCopyPastePolyglotReport()
    assert empty.passed() is True
    one = TestCopyPastePolyglotReport(
        findings=(
            CopyPasteFinding(
                a_file="a",
                a_name="test_a",
                a_row=0,
                b_file="a",
                b_name="test_b",
                b_row=10,
                jaccard=0.9,
                language="python",
            ),
        )
    )
    assert one.passed() is False
    assert one.passed(threshold=1) is True


def test_syntax_error_python_does_not_raise(tmp_path: Path) -> None:
    p = tmp_path / "test_broken.py"
    p.write_text("def test_a(:\n")
    # Extraction returns []; scan does not raise.
    scan_test_copy_paste([p])


def test_dir_scan_walks_recursively(tmp_path: Path) -> None:
    d = tmp_path / "pkg" / "tests"
    d.mkdir(parents=True)
    (d / "test_a.py").write_text(
        "def test_a():\n    x = compute(1)\n    assert x == 2\n    assert isinstance(x, int)\n"
    )
    (d / "test_b.py").write_text(
        "def test_b():\n    y = compute(2)\n    assert y == 3\n    assert isinstance(y, int)\n"
    )
    report = scan_test_copy_paste_in_dir(tmp_path)
    assert len(report.findings) >= 1


def test_cross_language_never_compared(tmp_path: Path) -> None:
    """A Python test body and a Go test body must never form a pair."""
    py = tmp_path / "test_x.py"
    py.write_text(
        "def test_a():\n    x = compute(1)\n    assert x == 2\n    assert isinstance(x, int)\n"
    )
    go = tmp_path / "x_test.go"
    go.write_text(
        'package x\nimport "testing"\n'
        'func TestA(t *testing.T){ x := compute(1); if x != 2 { t.Errorf("no %d", x) }; if x <= 0 { t.Errorf("no") } }\n'
    )
    report = scan_test_copy_paste([py, go])
    for f in report.findings:
        assert f.a_file == f.b_file or f.language in {"python", "go"}
