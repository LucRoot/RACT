"""B-014b: the turn summary draws the diff from the turn's own backup.

The before text comes from undo_backup.previous_version, with the backup id
taken from the turn.finished event. The after text is read from the project,
only for paths inside it. A bad id, a path outside the project, or no project
gives a plain line, never a crash and never a read outside the project.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ract import undo_backup
from ract.session_events import EventStream
from ract.session_render import PlainRenderer


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "state"
    home.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(home))
    monkeypatch.setenv("XDG_STATE_HOME", str(home))


def _turn(ws: Path) -> str:
    (ws / "src").mkdir(parents=True)
    (ws / "src" / "a.py").write_bytes(b"def add(a, b):\n    return a - b\n")
    with undo_backup.turn(ws) as backup:
        undo_backup.save_before_replace(ws, ["src/a.py"])
        (ws / "src" / "a.py").write_bytes(b"def add(a, b):\n    return a + b\n")
    return backup.turn_id


def _render(project: Path | None, changed: list[str], backup_id: str | None) -> str:
    out = io.StringIO()
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 23, 11, 0, tzinfo=timezone.utc),
    )
    renderer = PlainRenderer(out.write, project=project)
    stream.subscribe(renderer)
    stream.emit("turn.started", {}, turn=1)
    stream.emit(
        "turn.finished",
        {
            "outcome": "done",
            "verdict": "passed",
            "changed": changed,
            "diffstat": {},
            "backup_id": backup_id,
            "duration_ms": 0,
        },
        turn=1,
    )
    renderer.close()
    return out.getvalue()


def test_the_block_shows_the_change_from_the_backup(tmp_path, state):
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    text = _render(ws, ["src/a.py"], backup_id)
    assert "src/a.py: lines 1-2 -> 1-2, +1 -1" in text
    assert "return a - b" in text and "return a + b" in text
    assert "1 file, +1 -1" in text


def test_a_bad_backup_id_says_the_diff_is_not_available(tmp_path, state):
    ws = tmp_path / "ws"
    _turn(ws)
    text = _render(ws, ["src/a.py"], "../../escape/")
    assert "diff not available for src/a.py" in text


def test_a_path_outside_the_project_is_never_read(tmp_path, state):
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    outside = tmp_path / "secret.txt"
    outside.write_text("TOP SECRET\n", encoding="utf-8")
    text = _render(ws, ["../secret.txt"], backup_id)
    assert "TOP SECRET" not in text
    assert "diff not available for ../secret.txt" in text


def test_a_new_file_shows_as_a_new_file(tmp_path, state):
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    (ws / "src" / "fresh.py").write_text("x = 1\n", encoding="utf-8")
    text = _render(ws, ["src/fresh.py"], backup_id)
    assert "src/fresh.py: new file, 1 line" in text


def test_no_project_means_no_diff_block(tmp_path, state):
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    text = _render(None, ["src/a.py"], backup_id)
    assert ": lines " not in text


def test_the_summary_never_names_a_diff_command(tmp_path, state):
    # G-146 item 1: /diff does not exist yet (B-014c). No line may send the user there.
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    changed = [f"src/f{i:02d}.py" for i in range(25)]
    for name in changed:
        (ws / name).parent.mkdir(parents=True, exist_ok=True)
        (ws / name).write_text("x = 1\n", encoding="utf-8")
    text = _render(ws, changed, backup_id)
    assert "/diff" not in text
    assert "more files" in text


def test_a_file_over_the_size_cap_is_named_not_read(tmp_path, state):
    # G-146 item 2: a file over 8 MiB is never loaded; it is named instead.
    ws = tmp_path / "ws"
    backup_id = _turn(ws)
    big = ws / "src" / "huge.txt"
    with big.open("wb") as handle:
        handle.truncate(9 * 1024 * 1024)
    text = _render(ws, ["src/huge.txt"], backup_id)
    assert "src/huge.txt: too large to draw a diff" in text
    assert ": lines " not in text


def test_a_backup_id_that_is_a_path_is_refused(tmp_path, state):
    # B-070: the id is a name. A value that looks like a path is refused, not parsed.
    ws = tmp_path / "ws"
    _turn(ws)
    text = _render(ws, ["src/a.py"], r"..\..\escape")
    assert "diff not available for src/a.py" in text


def test_no_backup_id_means_no_diff_block(tmp_path, state):
    ws = tmp_path / "ws"
    _turn(ws)
    text = _render(ws, ["src/a.py"], None)
    assert ": lines " not in text


def test_an_absolute_path_as_the_backup_id_is_refused_before_any_folder_is_read(
    tmp_path, state
):
    # G-159: the id is checked as a name first; an absolute path never reaches a folder check.
    ws = tmp_path / "ws"
    _turn(ws)
    absolute = str(tmp_path.anchor) if tmp_path.anchor else "/"
    text = _render(ws, ["src/a.py"], absolute)
    assert "diff not available for src/a.py" in text
