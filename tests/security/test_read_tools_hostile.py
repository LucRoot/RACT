"""B-010a: hostile inputs to the read-only tools (ADR-0047 D2, D3, D4).

A cloned repository and a model's arguments are both untrusted. Every path goes
through the one resolver; .git, .ract, secret-shaped files and RACT's own config
are never read; a link or junction cannot lead out; a huge or binary file cannot
flood the conversation; a regex cannot hang the session; and a binary the
repository ships cannot stand in for ripgrep.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ract.tools import run_tool


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "src/../../outside.txt",
        "/etc/passwd",
        "C:/Windows/win.ini",
        "\\\\server\\share\\x",
        "a.py\x00.txt",
    ],
)
def test_a_path_out_of_the_project_is_refused(ws: Path, path: str) -> None:
    (ws.parent / "outside.txt").write_text("secret outside\n", encoding="utf-8")
    for tool, args in (
        ("read_file", {"path": path}),
        ("list_dir", {"path": path}),
        ("grep", {"pattern": "secret", "path": path}),
    ):
        result = run_tool(ws, tool, args)
        assert not result.is_ok(), (tool, path)
        assert "secret outside" not in (result.error or "")


@pytest.mark.parametrize(
    "rel",
    [
        ".git/config",
        ".ract/handshakes.json",
        ".env",
        "keys/server.pem",
        "ract.yaml",
        "sub/.git/HEAD",
    ],
)
def test_never_sent_files_are_not_read(ws: Path, rel: str) -> None:
    target = ws / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("TOKEN=never-leave-the-machine\n", encoding="utf-8")
    result = run_tool(ws, "read_file", {"path": rel})
    assert not result.is_ok()
    assert "never-leave-the-machine" not in (result.error or "")


def test_grep_never_returns_a_line_from_a_never_sent_file(ws: Path) -> None:
    (ws / ".env").write_text("TOKEN=never-leave-the-machine\n", encoding="utf-8")
    (ws / ".ract").mkdir()
    (ws / ".ract" / "notes.txt").write_text(
        "never-leave-the-machine\n", encoding="utf-8"
    )
    (ws / "ract.yaml").write_text(
        "api_key: never-leave-the-machine\n", encoding="utf-8"
    )
    for include_ignored in (False, True):
        result = run_tool(
            ws,
            "grep",
            {"pattern": "never-leave", "include_ignored": include_ignored},
        )
        assert result.is_ok(), result.error
        assert result.unwrap().facts["matches"] == []
        assert "never-leave-the-machine" not in result.unwrap().text


def test_glob_and_list_dir_never_name_a_never_sent_folder(ws: Path) -> None:
    (ws / ".ract").mkdir()
    (ws / ".ract" / "key.json").write_text("{}", encoding="utf-8")
    listed = run_tool(ws, "list_dir", {"path": ".", "include_ignored": True}).unwrap()
    assert ".ract" not in [e["name"] for e in listed.facts["entries"]]
    found = run_tool(ws, "glob", {"pattern": "**/*.json", "include_ignored": True})
    assert found.unwrap().facts["paths"] == []


def _junction(link: Path, target: Path) -> None:
    if os.name != "nt":
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            pytest.skip("cannot create a directory link here")
        return
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"mklink /J failed: {result.stderr.strip()}")


def test_a_junction_out_of_the_project_is_not_followed(ws: Path) -> None:
    outside = ws.parent / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("secret outside\n", encoding="utf-8")
    _junction(ws / "door", outside)

    assert not run_tool(ws, "read_file", {"path": "door/loot.txt"}).is_ok()
    grep = run_tool(ws, "grep", {"pattern": "secret outside", "include_ignored": True})
    assert grep.is_ok(), grep.error
    assert grep.unwrap().facts["matches"] == []
    listed = run_tool(ws, "glob", {"pattern": "**/*.txt", "include_ignored": True})
    assert listed.unwrap().facts["paths"] == []


def test_a_file_link_out_of_the_project_is_not_read(ws: Path) -> None:
    outside = ws.parent / "loot.txt"
    outside.write_text("secret outside\n", encoding="utf-8")
    try:
        os.symlink(outside, ws / "link.txt")
    except OSError:
        pytest.skip("symbolic links need a privilege this machine does not grant")
    result = run_tool(ws, "read_file", {"path": "link.txt"})
    assert not result.is_ok()


def test_a_huge_file_is_refused_by_size_without_reading_it(ws: Path) -> None:
    huge = ws / "huge.log"
    with open(huge, "wb") as fh:
        fh.truncate(80 * 1024 * 1024)  # sparse: 80 MiB of nothing, instantly
    started = time.perf_counter()
    result = run_tool(ws, "read_file", {"path": "huge.log"})
    assert time.perf_counter() - started < 5
    assert not result.is_ok()
    assert "MiB" in result.error


def test_a_catastrophic_regex_cannot_hang_the_session(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws / "slow.txt").write_text("a" * 40 + "b\n", encoding="utf-8")
    monkeypatch.setattr(
        "ract.tools.read._ripgrep", lambda root: None
    )  # Python fallback
    monkeypatch.setattr("ract.tools.read.GREP_TIMEOUT_SECONDS", 2.0)
    started = time.perf_counter()
    result = run_tool(ws, "grep", {"pattern": r"^(a+)+$"})
    assert time.perf_counter() - started < 10
    assert not result.is_ok()
    assert "took longer than" in result.error


def test_an_invalid_regex_is_a_refusal_with_a_hint(ws: Path) -> None:
    result = run_tool(ws, "grep", {"pattern": "(unclosed"})
    assert not result.is_ok()
    assert result.hint


@pytest.mark.skipif(
    os.name != "nt", reason="the working-folder search is Windows behavior"
)
def test_a_ripgrep_the_repository_ships_is_not_run(ws: Path) -> None:
    from ract.tools import read

    planted = ws / "rg.exe"
    shutil.copy(
        sys.executable, planted
    )  # any program at the name the search would find
    found = read._ripgrep(ws)
    assert found is None or ws.resolve() not in Path(found).resolve().parents
