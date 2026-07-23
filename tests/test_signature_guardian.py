__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from pathlib import Path

import pytest

from rootact.signature_guardian import SignatureGuardian, SignatureViolationError


def test_scan_finds_no_violations_for_valid_files(tmp_path: Path) -> None:
    valid = tmp_path / "valid.py"
    valid.write_text(
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n"
        "def hello():\n"
        "    pass\n",
        encoding="utf-8",
    )
    guardian = SignatureGuardian(tmp_path)
    assert guardian.scan() == []


def test_scan_reports_missing_markers(tmp_path: Path) -> None:
    missing = tmp_path / "missing.py"
    missing.write_text("def hello():\n    pass\n", encoding="utf-8")
    guardian = SignatureGuardian(tmp_path)
    violations = guardian.scan()
    assert len(violations) == 1
    assert violations[0]["path"] == str(missing)
    assert "__root_author__" in violations[0]["missing"]
    assert "__ract_name__" in violations[0]["missing"]
    assert "_ROOT_KNOT" in violations[0]["missing"]


def test_scan_reports_wrong_author_value(tmp_path: Path) -> None:
    wrong = tmp_path / "wrong.py"
    wrong.write_text(
        '__root_author__ = "Someone Else"\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n",
        encoding="utf-8",
    )
    guardian = SignatureGuardian(tmp_path)
    violations = guardian.scan()
    assert len(violations) == 1
    assert "__root_author__" in violations[0]["missing"]


def test_assert_intact_raises_on_violations(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def hello():\n    pass\n", encoding="utf-8")
    guardian = SignatureGuardian(tmp_path)
    with pytest.raises(SignatureViolationError):
        guardian.assert_intact()


def test_assert_intact_passes_when_clean(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text(
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n",
        encoding="utf-8",
    )
    guardian = SignatureGuardian(tmp_path)
    guardian.assert_intact()


def test_golden_hash_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.py"
    source.write_text(
        '__root_author__ = "Dr. Lucas Root, Ph.D."\n'
        '__ract_name__ = "RACT"\n'
        "_ROOT_KNOT = object()\n",
        encoding="utf-8",
    )
    guardian = SignatureGuardian(tmp_path)
    first = guardian.golden_hash()
    second = guardian.golden_hash()
    assert first == second
    assert len(first) == 64


def test_scan_skips_init_files(tmp_path: Path) -> None:
    init = tmp_path / "__init__.py"
    init.write_text("def hello():\n    pass\n", encoding="utf-8")
    guardian = SignatureGuardian(tmp_path)
    assert guardian.scan() == []
