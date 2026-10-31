"""B-212: a hard link planted at the old temporary name cannot redirect a write.

``tools/write.py`` wrote through ``.NAME.ract-tmp``; a repository could ship a
hard link at that name to a file outside the workspace, and the write landed
there. The temporary file is now made fresh with a random name.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ract.atomic_write import write_atomic
from ract.tools import write as write_tool


def _plant(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "project"
    root.mkdir()
    target = root / "a.py"
    target.write_bytes(b"x = 1\n")
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"keep me\n")
    planted = root / ".a.py.ract-tmp"
    try:
        os.link(outside, planted)
    except OSError as exc:
        pytest.skip(f"no hard link here: {exc}")
    return root, target, outside


def test_the_write_tool_does_not_write_through_a_planted_temp_link(tmp_path: Path) -> None:
    _root, target, outside = _plant(tmp_path)
    write_tool._replace(target, b"x = 2\n")
    assert target.read_bytes() == b"x = 2\n"
    assert outside.read_bytes() == b"keep me\n"


def test_write_atomic_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "f.txt"
    write_atomic(path, b"one\n")
    write_atomic(path, b"two\n")
    assert path.read_bytes() == b"two\n"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_write_atomic_cleans_up_when_the_rename_fails(tmp_path: Path, monkeypatch) -> None:
    def refuse(src: object, dst: object) -> None:
        raise OSError("rename refused")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError):
        write_atomic(tmp_path / "f.txt", b"x\n")
    assert list(tmp_path.iterdir()) == []


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX file modes (WSL run)")


@posix_only
def test_an_executable_script_keeps_its_mode(tmp_path: Path) -> None:
    script = tmp_path / "run.sh"
    script.write_bytes(b"#!/bin/sh\necho one\n")
    script.chmod(0o755)
    write_tool._replace(script, b"#!/bin/sh\necho two\n")
    assert stat.S_IMODE(script.stat().st_mode) == 0o755


@posix_only
def test_a_plain_file_keeps_its_mode(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes(b"one\n")
    path.chmod(0o644)
    write_atomic(path, b"two\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@posix_only
def test_a_new_file_gets_the_umask_default(tmp_path: Path) -> None:
    old = os.umask(0o027)
    try:
        write_atomic(tmp_path / "new.txt", b"x\n")
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "new.txt").stat().st_mode) == 0o640
