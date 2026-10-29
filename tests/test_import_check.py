"""B-102 (S2 D10): a written file that imports a name its project module lacks is not done.

The check reads source only; no project code is imported or run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.executor.steps import Executor
from ract.import_check import missing_names
from ract.manager import Plan, Step
from tests.test_reasoning_model_handling import _Adapter, _response, _Router

WRIGHT = "from src import NOTE\n\n\ndef test_note():\n    assert NOTE == 'two'\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "notes.py").write_text('NOTE = "two"\n', encoding="utf-8")
    (tmp_path / "tests").mkdir()
    return tmp_path


def _names(repo: Path, text: str, path: str = "tests/test_notes.py") -> list[str]:
    return [m.describe() for m in missing_names(repo, path, text)]


def test_wrights_case_is_found(repo: Path) -> None:
    assert _names(repo, WRIGHT) == [
        "line 1: imports NOTE from src, which does not define it"
    ]


def test_a_correct_import_passes(repo: Path) -> None:
    assert _names(repo, "from src.notes import NOTE\nfrom src import notes\n") == []


def test_a_package_that_reexports_the_name_passes(repo: Path) -> None:
    (repo / "src" / "__init__.py").write_text(
        "from .notes import NOTE\n", encoding="utf-8"
    )
    assert _names(repo, WRIGHT) == []


def test_a_relative_import(repo: Path) -> None:
    good = "from .notes import NOTE\n"
    bad = "from .notes import MISSING\n"
    assert _names(repo, good, "src/use.py") == []
    assert _names(repo, bad, "src/use.py") == [
        "line 1: imports MISSING from .notes, which does not define it"
    ]


def test_a_syntax_error_is_left_to_the_write_gate(repo: Path) -> None:
    assert _names(repo, "from src import (\n") == []


def test_third_party_and_standard_library_are_not_checked(repo: Path) -> None:
    assert (
        _names(repo, "from requests import nothing_here\nfrom os import nope\n") == []
    )


@pytest.mark.parametrize(
    "module_text",
    ["from .other import *\n", "def __getattr__(name):\n    return 1\n"],
    ids=["star-import", "module-getattr"],
)
def test_a_module_that_cannot_be_read_with_certainty_is_not_checked(
    repo: Path, module_text: str
) -> None:
    (repo / "src" / "__init__.py").write_text(module_text, encoding="utf-8")
    assert _names(repo, WRIGHT) == []


def test_a_namespace_package_is_not_checked(repo: Path) -> None:
    (repo / "src" / "__init__.py").unlink()
    assert _names(repo, WRIGHT) == []


def test_a_name_bound_under_a_guard_counts(repo: Path) -> None:
    (repo / "src" / "__init__.py").write_text(
        "try:\n    from .notes import NOTE\nexcept ImportError:\n    NOTE = None\n",
        encoding="utf-8",
    )
    assert _names(repo, WRIGHT) == []


def test_a_step_that_writes_wrights_file_is_refused(repo: Path) -> None:
    plan = Plan(
        assumption="a",
        confidence=0.9,
        steps=[
            Step(
                action="Add tests/test_notes.py",
                provider_hint="x",
                expected_artifact="tests/test_notes.py",
            )
        ],
    )
    result = Executor(_Router(_Adapter(_response(WRIGHT))), project_dir=repo).execute(
        intent="i", plan=plan
    )
    assert not result.is_ok()
    assert "imports a name that does not exist" in result.error
    assert "NOTE from src" in result.error
    assert not (repo / "tests" / "test_notes.py").exists()
