"""B-075b: a cloned repository's legacy `.rack/` folder, read by the migration.

RACT renames a legacy `.rack/` folder to `.ract/` on the first run. A
repository can ship that folder, so its content becomes state RACT reads
later (hooks, sessions, snapshots). The tests check that a shipped hook is
migrated and still needs `ract trust`, that existing state is never overwritten,
and that a `.rack` file or a very large tree is handled without harm.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from ract import trust
from ract.workspace_state import migrate_rack_to_ract

MIB = 1024 * 1024


def _plant(root: Path, parts: tuple[str, ...], data: bytes) -> Path:
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def test_a_shipped_hook_is_migrated_and_still_needs_trust(tmp_path: Path) -> None:
    hook = {"command": "echo shipped"}
    _plant(tmp_path, (".rack", "hooks", "pre.json"), json.dumps(hook).encode("utf-8"))

    assert migrate_rack_to_ract(tmp_path) == "migrated"

    assert (tmp_path / ".ract" / "hooks" / "pre.json").is_file()
    assert not (tmp_path / ".rack").exists()
    names = [item.name for item in trust.trust_items(tmp_path)]
    assert "pre" in names, "the migrated hook is not listed for trust"
    assert not trust.is_trusted(tmp_path), (
        "a migrated repository must not be trusted by itself"
    )


def test_both_folders_present_nothing_is_overwritten_and_the_user_is_told(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = _plant(tmp_path, (".rack", "sessions", "s1.json"), b'{"legacy": true}')
    modern = _plant(tmp_path, (".ract", "sessions", "s1.json"), b'{"modern": true}')

    assert migrate_rack_to_ract(tmp_path) == "warned_both"

    assert legacy.read_bytes() == b'{"legacy": true}'
    assert modern.read_bytes() == b'{"modern": true}'
    assert "BOTH" in capsys.readouterr().err


def test_a_rack_that_is_a_file_is_not_renamed_into_the_state_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".rack").write_bytes(b"not a folder")

    result = migrate_rack_to_ract(tmp_path)

    assert not ((tmp_path / ".ract").is_file()), (
        f"a file named .rack was renamed to a file named .ract (result {result!r})"
    )
    assert result == "skipped_not_a_folder"
    assert (tmp_path / ".rack").read_bytes() == b"not a folder"
    assert "is not a folder" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_a_junctioned_legacy_folder_is_not_renamed_into_the_state_folder(
    tmp_path: Path,
) -> None:
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_bytes(b"outside")
    project = tmp_path / "project"
    project.mkdir()
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(project / ".rack"), str(outside)],
        capture_output=True,
        text=True,
    )
    if made.returncode != 0:
        pytest.skip(f"mklink /J failed: {made.stderr.strip()}")

    assert migrate_rack_to_ract(project) == "skipped_not_a_folder"

    assert not (project / ".ract").exists()
    assert (outside / "keep.txt").read_bytes() == b"outside"


def test_a_very_large_legacy_tree_migrates_in_one_rename(tmp_path: Path) -> None:
    sessions = tmp_path / ".rack" / "sessions"
    sessions.mkdir(parents=True)
    for index in range(2000):
        (sessions / f"s{index}.json").write_bytes(b"{}")

    started = time.monotonic()
    assert migrate_rack_to_ract(tmp_path) == "migrated"
    elapsed = time.monotonic() - started

    assert len(list((tmp_path / ".ract" / "sessions").glob("*.json"))) == 2000
    assert elapsed < 5.0, f"migration took {elapsed:.2f} s"


def test_a_symlinked_legacy_folder_is_not_renamed_into_the_state_folder(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    try:
        os.symlink(outside, project / ".rack", target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks need a privilege this account lacks: {exc}")

    migrate_rack_to_ract(project)

    assert not (project / ".ract").is_symlink(), (
        "a link to outside the project became the state folder"
    )
