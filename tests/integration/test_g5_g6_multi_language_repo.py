"""Integration: polyglot G5/G6 across a mixed .py/.js/.ts/.rs/.go repo (module_08)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.antilazy.dead_code_polyglot import scan_dead_code_in_dir
from ract.antilazy.test_copy_paste_polyglot import scan_test_copy_paste_in_dir


@pytest.fixture()
def polyglot_repo(tmp_path: Path) -> Path:
    """Materialise a small mixed-language repo under ``tmp_path``.

    Layout::

        tmp_path/
          py/mod.py            # dead: `orphan_py`; used: `used_py`
          js/mod.js            # dead: `orphan_js`; used: `used_js`
          ts/mod.ts            # dead: `OrphanType`; used: `UsedType`
          rs/mod.rs            # dead: `orphan_rs`; used: `used_rs`
          go/mod.go            # dead: `OrphanGo`; used: `UsedGo`
          tests/test_a.py      # copy-paste pair test_a / test_b
          tests/x.test.js      # copy-paste pair it('does a') / it('does b')
          tests/x_test.go      # copy-paste pair TestA / TestB
    """
    root = tmp_path

    # ----- production code -----
    (root / "py").mkdir()
    (root / "py" / "mod.py").write_text(
        "def used_py():\n    return 1\n"
        "def orphan_py():\n    return 2\n"
        "print(used_py())\n"
    )

    (root / "js").mkdir()
    (root / "js" / "mod.js").write_text(
        "function used_js(x) { return x; }\n"
        "function orphan_js(x) { return x + 1; }\n"
        "console.log(used_js(1));\n"
    )

    (root / "ts").mkdir()
    (root / "ts" / "mod.ts").write_text(
        "type UsedType = string;\n"
        "type OrphanType = number;\n"
        "const x: UsedType = 'a';\n"
        "console.log(x);\n"
    )

    (root / "rs").mkdir()
    (root / "rs" / "mod.rs").write_text(
        "fn used_rs() -> i32 { 1 }\n"
        "fn orphan_rs() -> i32 { 2 }\n"
        'fn main() { println!("{}", used_rs()); }\n'
    )

    (root / "go").mkdir()
    (root / "go" / "mod.go").write_text(
        "package main\n"
        "type UsedGo struct{ X int }\n"
        "type OrphanGo struct{ Y int }\n"
        "func main() { _ = UsedGo{X: 1} }\n"
    )

    # ----- tests -----
    (root / "tests").mkdir()
    (root / "tests" / "test_a.py").write_text(
        "def test_a():\n"
        "    x = compute(1)\n"
        "    assert x == 2\n"
        "    assert isinstance(x, int)\n"
        "def test_b():\n"
        "    y = compute(2)\n"
        "    assert y == 3\n"
        "    assert isinstance(y, int)\n"
    )
    (root / "tests" / "x.test.js").write_text(
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
    (root / "tests" / "x_test.go").write_text(
        'package x\nimport "testing"\n'
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

    return root


def test_g5_dead_code_across_all_five_languages(polyglot_repo: Path) -> None:
    """G5 must land verdicts with language attribution for each MVP language."""
    report = scan_dead_code_in_dir(polyglot_repo)
    by_lang: dict[str, set[str]] = {}
    for c in report.candidates:
        by_lang.setdefault(c.language, set()).add(c.identifier)

    # Every MVP language MUST surface its orphan.
    assert "orphan_py" in by_lang.get("python", set()), by_lang
    assert "orphan_js" in by_lang.get("javascript", set()), by_lang
    assert "OrphanType" in by_lang.get("typescript", set()), by_lang
    assert "orphan_rs" in by_lang.get("rust", set()), by_lang
    assert "OrphanGo" in by_lang.get("go", set()), by_lang

    # And NONE of the used identifiers.
    all_reported = {c.identifier for c in report.candidates}
    for used in ("used_py", "used_js", "UsedType", "used_rs", "UsedGo"):
        assert used not in all_reported, f"{used} should not be flagged"


def test_g6_copy_paste_across_multiple_languages(polyglot_repo: Path) -> None:
    """G6 must surface copy-paste pairs in Python, JS, and Go simultaneously."""
    report = scan_test_copy_paste_in_dir(polyglot_repo)
    by_lang: dict[str, int] = {}
    for f in report.findings:
        by_lang[f.language] = by_lang.get(f.language, 0) + 1

    assert by_lang.get("python", 0) >= 1, by_lang
    assert by_lang.get("javascript", 0) >= 1, by_lang
    assert by_lang.get("go", 0) >= 1, by_lang


def test_g6_scans_tests_across_languages(polyglot_repo: Path) -> None:
    """tests_scanned reflects the union of extracted test bodies."""
    report = scan_test_copy_paste_in_dir(polyglot_repo)
    # 2 Python tests, 2 JS callback tests + 1 describe callback,
    # 2 Go tests. Exact count is implementation-detail, but at
    # least 6 test bodies must have been scanned.
    assert report.tests_scanned >= 6, report.tests_scanned


def test_g5_report_has_no_unsupported_languages_in_repo(
    polyglot_repo: Path,
) -> None:
    """The MVP grammars are all installed in the CI + dev extras;
    unsupported_languages must be empty on this fixture."""
    report = scan_dead_code_in_dir(polyglot_repo)
    assert report.unsupported_languages == ()


def test_g6_report_has_no_unsupported_languages_in_repo(
    polyglot_repo: Path,
) -> None:
    report = scan_test_copy_paste_in_dir(polyglot_repo)
    assert report.unsupported_languages == ()


def test_scan_ignores_vendor_directories(polyglot_repo: Path) -> None:
    """Files under node_modules etc. must be silently ignored."""
    (polyglot_repo / "node_modules").mkdir()
    (polyglot_repo / "node_modules" / "vendored.js").write_text(
        "function vendored_orphan(){ return 1; }\n"
    )
    report = scan_dead_code_in_dir(polyglot_repo)
    assert not any(c.identifier == "vendored_orphan" for c in report.candidates)
