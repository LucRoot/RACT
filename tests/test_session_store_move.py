"""B-079: ``ract session ...`` keeps its store in ``.ract/sessions`` (decision X, D-059).

Sessions saved by an older release in ``.ract_sessions/`` are copied into the new
store once, with a notice; the old folder is left as it was.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ract.cli import _session_command
from ract.session_store import SessionStore


@pytest.fixture
def in_tmp(tmp_path: Path):
    original = os.getcwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(original)


def _old_session(root: Path, sid: str) -> None:
    old = root / ".ract_sessions"
    old.mkdir(exist_ok=True)
    (old / f"{sid}.json").write_text(json.dumps({"intent": sid}), encoding="utf-8")


def test_the_default_store_is_in_the_ract_folder(in_tmp: Path) -> None:
    store = SessionStore()
    assert store.base_dir == Path(".ract") / "sessions"
    assert (in_tmp / ".ract" / "sessions").is_dir()
    assert not (in_tmp / ".ract_sessions").exists()


def test_session_list_reads_the_new_store(in_tmp: Path, capsys) -> None:
    SessionStore(in_tmp / ".ract" / "sessions").save("s-new", {"intent": "x"})
    assert _session_command(["list", "--json"]) == 0
    out = capsys.readouterr().out
    try:
        listed = json.loads(out)
    except json.JSONDecodeError as exc:
        pytest.fail(f"--json stdout was polluted: {out[:300]!r} ({exc})")
    assert listed == ["s-new"]
    assert not (in_tmp / ".ract_sessions").exists()


def test_old_sessions_are_copied_once_with_a_notice(in_tmp: Path, capsys) -> None:
    _old_session(in_tmp, "s-old")
    assert _session_command(["list", "--json"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == ["s-old"]
    assert ".ract_sessions" in out.err and str(Path(".ract/sessions")) in out.err
    assert (in_tmp / ".ract" / "sessions" / "s-old.json").is_file()
    assert (in_tmp / ".ract_sessions" / "s-old.json").is_file()

    assert _session_command(["list", "--json"]) == 0
    again = capsys.readouterr()
    assert json.loads(again.out) == ["s-old"]
    assert again.err == ""


def test_a_session_already_in_the_new_store_is_not_overwritten(
    in_tmp: Path, capsys
) -> None:
    _old_session(in_tmp, "s-both")
    new = SessionStore(in_tmp / ".ract" / "sessions")
    new.save("s-both", {"intent": "newer"})
    assert _session_command(["list", "--json"]) == 0
    capsys.readouterr()
    assert new.load("s-both")["intent"] == "newer"


def test_an_explicit_store_is_used_as_given(in_tmp: Path, capsys) -> None:
    _old_session(in_tmp, "s-old")
    assert _session_command(["list", "--json", "--store", ".ract_sessions"]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == ["s-old"]
    assert out.err == ""
    assert not (in_tmp / ".ract" / "sessions").exists()


def test_old_entries_that_are_not_session_files_are_not_copied(
    in_tmp: Path, capsys
) -> None:
    old = in_tmp / ".ract_sessions"
    old.mkdir()
    (old / "notes.txt").write_text("x", encoding="utf-8")
    (old / "bad name.json").write_text("{}", encoding="utf-8")
    (old / "dir.json").mkdir()
    assert _session_command(["list", "--json"]) == 0
    capsys.readouterr()
    assert sorted(p.name for p in (in_tmp / ".ract" / "sessions").iterdir()) == [
        ".moved-from-ract_sessions"
    ]
