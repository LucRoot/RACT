"""L-141 decision 3: the before text for the turn summary, by backup id, never by path.

`turn.finished` will carry `backup_id`, the turn's backup folder name. The
renderer asks `undo_backup.previous_version` for a file's previous bytes. The
id and the path come from an event, so both are checked: the id is a name,
the folder's manifest belongs to this repository, the path is one the turn
saved, and nothing is read through a link.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract import undo_backup


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))


def _turn(ws: Path) -> str:
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.py").write_bytes(b"old = 1\n")
    with undo_backup.turn(ws) as backup:
        undo_backup.save_before_replace(ws, ["src/a.py"])
        (ws / "src" / "a.py").write_bytes(b"new = 2\n")
    return backup.turn_id


def test_the_saved_bytes_come_back_by_id(tmp_path: Path, state: None) -> None:
    ws = tmp_path / "ws"
    backup_id = _turn(ws)

    assert undo_backup.previous_version(ws, backup_id, "src/a.py") == b"old = 1\n"


@pytest.mark.parametrize("backup_id", ["../x", "..", "", ".hidden", "a/b", "C:x"])
def test_an_id_that_is_not_a_name_is_refused(
    tmp_path: Path, state: None, backup_id: str
) -> None:
    ws = tmp_path / "ws"
    _turn(ws)

    with pytest.raises(ValueError):
        undo_backup.previous_version(ws, backup_id, "src/a.py")


@pytest.mark.parametrize(
    "path", ["../../outside.txt", "/etc/passwd", ".git/config", "src/../../x", "C:/x"]
)
def test_a_path_outside_the_turn_is_refused(
    tmp_path: Path, state: None, path: str
) -> None:
    ws = tmp_path / "ws"
    backup_id = _turn(ws)

    with pytest.raises(ValueError):
        undo_backup.previous_version(ws, backup_id, path)


def test_a_path_the_turn_did_not_save_gives_nothing(
    tmp_path: Path, state: None
) -> None:
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    folder = undo_backup.turns_dir(ws) / backup_id
    (folder / "src" / "planted.py").write_bytes(b"not saved by RACT\n")

    assert undo_backup.previous_version(ws, backup_id, "src/planted.py") is None


def test_another_repositorys_turn_gives_nothing(tmp_path: Path, state: None) -> None:
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    manifest = undo_backup.turns_dir(ws) / backup_id / undo_backup.MANIFEST
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["root"] = "somewhere-else"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    assert undo_backup.previous_version(ws, backup_id, "src/a.py") is None


def test_a_saved_file_replaced_by_a_link_is_not_read(
    tmp_path: Path, state: None
) -> None:
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    secret = tmp_path / "secret.txt"
    secret.write_text("not for the screen", encoding="utf-8")
    saved = undo_backup.turns_dir(ws) / backup_id / "src" / "a.py"
    saved.unlink()
    try:
        saved.symlink_to(secret)
    except OSError:
        pytest.skip("this account cannot create symbolic links (shown on Linux, B-046)")

    assert undo_backup.previous_version(ws, backup_id, "src/a.py") is None


def test_a_saved_file_over_the_cap_is_not_read(tmp_path: Path, state: None) -> None:
    # G-141: the summary must not load a huge saved file into memory.
    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True)
    big = ws / "data" / "big.bin"
    big.write_bytes(b"x" * (undo_backup.MAX_PREVIOUS_VERSION_BYTES + 1))
    with undo_backup.turn(ws) as backup:
        undo_backup.save_before_replace(ws, ["data/big.bin"])
        big.write_bytes(b"small now")

    assert undo_backup.previous_version(ws, backup.turn_id, "data/big.bin") is None
