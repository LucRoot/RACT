__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from pathlib import Path

from ract.root_knot_guardian import check, ensure_markers, fix, missing_markers, scan


def test_missing_markers_detects_absence() -> None:
    assert missing_markers("print('hello')") == [
        '__root_author__ = "Dr. Lucas Root, Ph.D."',
        '__ract_name__ = "RACT"',
        "_ROOT_KNOT = object()",
    ]


def test_missing_markers_empty_when_present() -> None:
    src = (
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n"
        "x = 1\n"
    )
    assert missing_markers(src) == []


def test_ensure_markers_inserts_at_top() -> None:
    result = ensure_markers("x = 1\n")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in result
    assert '__ract_name__ = "RACT"' in result
    assert "_ROOT_KNOT = object()" in result
    assert result.startswith('__root_author__ = "Dr. Lucas Root, Ph.D."')


def test_ensure_markers_preserves_future_import() -> None:
    src = "from __future__ import annotations\n\nx = 1\n"
    result = ensure_markers(src)
    lines = result.splitlines()
    assert lines[0] == "from __future__ import annotations"
    assert lines[1] == '__root_author__ = "Dr. Lucas Root, Ph.D."'
    assert lines[2] == '__ract_name__ = "RACT"'
    assert lines[3] == "_ROOT_KNOT = object()"


def test_scan_finds_missing_markers(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text(
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n"
        "x = 1\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    init = tmp_path / "__init__.py"
    init.write_text("x = 1\n", encoding="utf-8")

    violations = scan(tmp_path)
    assert len(violations) == 1
    assert violations[0][0] == str(bad)


def test_fix_repairs_files(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    assert fix(tmp_path) == 1
    content = bad.read_text(encoding="utf-8")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert '__ract_name__ = "RACT"' in content
    assert "_ROOT_KNOT = object()" in content


def test_check_returns_true_when_clean(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text(
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n"
        "x = 1\n",
        encoding="utf-8",
    )
    assert check(tmp_path) is True


def test_check_returns_false_when_violation(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("x = 1\n", encoding="utf-8")
    assert check(tmp_path) is False
