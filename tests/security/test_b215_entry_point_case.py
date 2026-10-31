"""B-215: entry-point and written-file names are matched case-folded.

``is_entry_point`` compared names exactly: ``PYTEST.INI``, ``Pyproject.toml``,
``TOX.INI``, ``MAKEFILE``, ``Package.json`` and ``sub/Conftest.py`` were not
entry points, though Windows, macOS and WSL under /mnt/c open them by any case,
so an allowlisted ``pytest`` would run changed configuration without asking.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.policy.allowlist import is_entry_point
from ract.policy.matcher import classify

NAMES = ["pytest.ini", "pyproject.toml", "tox.ini", "makefile", "package.json", "sub/conftest.py"]


def _cases(name: str) -> list[str]:
    head, _, tail = name.rpartition("/")
    prefix = f"{head}/" if head else ""
    return [prefix + tail.upper(), prefix + tail.capitalize(), prefix + tail.swapcase()]


@pytest.mark.parametrize("name", [c for n in NAMES for c in _cases(n)])
def test_an_entry_point_in_any_case_is_an_entry_point(name: str) -> None:
    assert is_entry_point(name)


@pytest.mark.parametrize("name", ["TESTS/TEST_CALC.PY", "Jest.Config.JS", "SRC/App.Test.TS"])
def test_test_files_and_config_families_in_any_case(name: str) -> None:
    assert is_entry_point(name)


def test_an_ordinary_file_is_still_not_an_entry_point() -> None:
    assert not is_entry_point("src/Calc.py")
    assert not is_entry_point("docs/README.MD")


def test_a_written_file_named_in_another_case_asks(tmp_path: Path) -> None:
    match = classify(
        ["pytest", "TESTS/Test_Calc.py"],
        None,
        tmp_path,
        model_written=frozenset({"tests/test_calc.py"}),
    )
    assert "written in this session" in match.reason, match
