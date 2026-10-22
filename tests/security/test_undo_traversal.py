"""S-028: `/undo` must never read a manifest a repository could ship, and
must never write, copy or delete outside the workspace.

From the manager's proof of concept (G-065): a manifest with
`saved: ["../payload.txt"]` and `after: {"../payload.txt": null}` made
`ract undo` write attacker content next to the repository. Every test
asserts that nothing outside the workspace changed and that the refused
entries are listed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ract import undo_backup
from tests.test_headless import _ract


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "repo"
    ws.mkdir()
    (ws / "ract.yaml").write_text("providers: {}\n", encoding="utf-8")
    return ws


def _plant(folder: Path, entries: dict[str, bytes], manifest: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for rel, data in entries.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _state_folder(ws: Path, name: str = "20991231T000000000000Z-aaaaaa") -> Path:
    return undo_backup.turns_dir(ws) / name


def _manifest(ws: Path, saved: list[str], created: list[str] | None = None) -> dict:
    paths = [*saved, *(created or [])]
    return {
        "kind": "turn",
        "turn": "x",
        "root": undo_backup.repository_key(ws),
        "saved": saved,
        "created": created or [],
        "after": {p: None for p in paths},
        "done": False,
    }


def test_a_manifest_shipped_inside_the_repository_is_ignored(tmp_path: Path) -> None:
    # The G-065 PoC, end to end through the CLI.
    ws = _workspace(tmp_path)
    shipped = ws / ".ract" / "undo" / "20991231T000000Z-evil00"
    _plant(
        shipped,
        {"../payload.txt": b"attacker\n"},
        {
            "kind": "turn",
            "saved": ["../payload.txt"],
            "created": [],
            "after": {"../payload.txt": None},
            "done": False,
        },
    )
    outside = tmp_path / "payload.txt"

    result = _ract(ws, "undo", "--config", "ract.yaml")

    assert not outside.exists()
    assert "nothing to undo" in result.stdout


@pytest.mark.parametrize(
    "entry",
    [
        "../payload.txt",
        "sub/../../payload.txt",
        "/tmp/payload.txt",
        "C:/payload.txt",
        "C:payload.txt",
        "\\\\server\\share\\payload.txt",
        ".git/hooks/pre-commit",
        ".ract/undo/x",
        "",
        "./",
    ],
)
def test_entries_outside_the_workspace_are_refused(tmp_path: Path, entry: str) -> None:
    ws = _workspace(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    folder = _state_folder(ws)
    _plant(folder, {"ok.txt": b"restored\n"}, _manifest(ws, [entry, "ok.txt"]))

    result = undo_backup.undo(ws, force=True)

    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert not (ws / ".git").exists() and not (ws / ".ract" / "undo" / "x").exists()
    assert result.refused and result.refused[0][0] == entry
    assert any(line.startswith("refused ") for line in result.lines("undo"))
    # The valid entry in the same manifest still goes through.
    assert (ws / "ok.txt").read_bytes() == b"restored\n"


def test_a_created_entry_pointing_outside_is_never_deleted(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    _plant(_state_folder(ws), {}, _manifest(ws, [], created=["../victim.txt"]))

    result = undo_backup.undo(ws, force=True)

    assert victim.read_text(encoding="utf-8") == "keep\n"
    assert result.refused


def test_a_path_through_a_symlink_that_leaves_the_workspace_is_refused(
    tmp_path: Path,
) -> None:
    ws = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, ws / "link", target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot create symbolic links")
    _plant(
        _state_folder(ws), {"link/x.txt": b"attacker\n"}, _manifest(ws, ["link/x.txt"])
    )

    result = undo_backup.undo(ws, force=True)

    assert not (outside / "x.txt").exists()
    assert result.refused


def test_a_manifest_recorded_for_another_repository_is_refused(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    manifest = _manifest(ws, ["ok.txt"])
    manifest["root"] = "somewhere-else"
    _plant(_state_folder(ws), {"ok.txt": b"x\n"}, manifest)

    result = undo_backup.undo(ws)

    assert result.folder is None and not (ws / "ok.txt").exists()


def test_backups_live_outside_the_workspace(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    (ws / "a.txt").write_text("one\n", encoding="utf-8")
    with undo_backup.turn(ws) as backup:
        undo_backup.save_before_replace(ws, ["a.txt"])
        (ws / "a.txt").write_text("two\n", encoding="utf-8")

    assert not (ws / ".ract" / "undo").exists()
    assert ws.resolve() not in backup.folder.resolve().parents
    assert undo_backup.undo(ws).restored == ["a.txt"]
