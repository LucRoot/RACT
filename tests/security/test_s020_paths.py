"""S-020 (AUD-014, AUD-015): reserved names, 8.3 short names and hard links.

Hostile first: every reserved device name Microsoft lists (COM0, LPT0, the
superscript forms, CONIN$, CONOUT$, CLOCK$) is refused; an existing 8.3 alias
of another name is refused; a write through a hard link to a file outside the
project is refused. Then the over-refusal is gone: ``a~1.txt`` and
``notes~2`` are ordinary names on a Windows volume.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from ract.workspace_path import resolve_workspace_path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / ".git" / "hooks").mkdir(parents=True)
    return root


def _code(
    root: Path, raw: str, *, purpose: str = "read", windows: bool | None = None
) -> str:
    result = resolve_workspace_path(root, raw, purpose=purpose, windows=windows)  # type: ignore[arg-type]
    if result.value is not None:
        return "ok"
    assert result.hint
    return result.provenance[-1].removeprefix("refused:")


def _short_name(path: Path) -> str | None:
    buffer = ctypes.create_unicode_buffer(32768)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer)):  # type: ignore[attr-defined]
        return None
    name = Path(buffer.value).name
    return name if name != path.name else None


# --- AUD-014: reserved names --------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "src/COM¹",
        "COM².txt",
        "lpt³.log",
        "com0",
        "LPT0.txt",
        "CONIN$",
        "src/conout$.txt",
        "CLOCK$",
    ],
)
def test_every_reserved_device_name_is_refused(project: Path, raw: str) -> None:
    assert _code(project, raw, windows=True) == "reserved_device_name"


def test_names_that_only_start_like_a_device_are_files(project: Path) -> None:
    for raw in ("docs/com10.md", "src/console.py", "auxiliary/a.txt", "clock.txt"):
        assert _code(project, raw, windows=True) == "ok", raw


# --- AUD-014: short names, asked of the volume --------------------------------


@pytest.mark.skipif(os.name != "nt", reason="needs a Windows volume")
def test_an_existing_alias_of_another_name_is_refused(project: Path) -> None:
    alias = _short_name(project / ".git")
    if alias is None:
        pytest.skip("8.3 names are not made on this volume")
    assert _code(project, f"{alias}/config", purpose="write") == "short_name"
    long_dir = project / "src" / "Program Files Long"
    long_dir.mkdir()
    alias = _short_name(long_dir)
    assert alias is not None
    assert _code(project, f"src/{alias}/x.py", purpose="write") == "short_name"


@pytest.mark.skipif(os.name != "nt", reason="needs a Windows volume")
def test_a_name_of_short_shape_that_is_itself_is_a_file(project: Path) -> None:
    assert _code(project, "src/a~1.txt", purpose="write") == "ok"  # new file
    (project / "src" / "notes~2").write_text("x\n", encoding="utf-8")
    assert _code(project, "src/notes~2", purpose="write") == "ok"  # its own name


# --- AUD-015: hard links ------------------------------------------------------


def _hard_link(project: Path) -> Path:
    outside = project.parent / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("keep\n", encoding="utf-8")
    link = project / "src" / "hl.txt"
    try:
        os.link(secret, link)
    except OSError as exc:
        pytest.skip(f"hard links are not available here: {exc}")
    return link


def test_a_write_through_a_hard_link_is_refused(project: Path) -> None:
    _hard_link(project)
    assert _code(project, "src/hl.txt", purpose="write") == "hard_link"


def test_reading_a_hard_linked_file_is_allowed(project: Path) -> None:
    _hard_link(project)
    assert _code(project, "src/hl.txt", purpose="read") == "ok"


def test_the_executor_does_not_write_through_a_hard_link(project: Path) -> None:
    from ract.executor import Executor
    from ract.manager import Plan, Step
    from tests.test_executor import FakeAdapter, FakeRouter

    _hard_link(project)
    executor = Executor(
        FakeRouter(FakeAdapter("mock", "changed\n")), project_dir=project
    )
    plan = Plan(
        assumption="x",
        confidence=1.0,
        steps=[
            Step(action="edit", provider_hint="mock", expected_artifact="src/hl.txt")
        ],
    )
    result = executor.execute(intent="edit", plan=plan)
    assert not result.is_ok()
    assert (project.parent / "outside" / "secret.txt").read_text(
        encoding="utf-8"
    ) == "keep\n"


def test_a_file_with_one_name_is_written(project: Path) -> None:
    (project / "src" / "one.txt").write_text("x\n", encoding="utf-8")
    assert _code(project, "src/one.txt", purpose="write") == "ok"
