"""B-110 D6: /checkpoint lists the checkpoints numbered; /restore N goes back to one.

``/restore`` is ``/undo`` repeated, newest first, with the same digest rule:
a file the operator changed since RACT wrote it is skipped and named, and the
walk stops there, so an older turn is never reversed under a newer one.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ract import undo_backup
from tests.test_diff_and_undo_list import _shown
from tests.test_undo import _turn


def _three_turns(root: Path) -> list[undo_backup.TurnBackup]:
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    return [
        _turn(root, {"a.txt": "two\n"}),
        _turn(root, {"a.txt": "three\n", "b.txt": "made by turn 2\n"}),
        _turn(root, {"c.txt": "made by turn 3\n"}),
    ]


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8") if path.exists() else None


def test_restore_reverses_every_later_turn_newest_first(tmp_path: Path) -> None:
    first, _second, _third = _three_turns(tmp_path)

    results = undo_backup.restore(tmp_path, first.turn_id)

    assert [r.removed for r in results] == [["c.txt"], ["b.txt"]]
    assert _read(tmp_path, "a.txt") == "two\n"  # as the first turn left it
    assert _read(tmp_path, "b.txt") is None and _read(tmp_path, "c.txt") is None
    # /redo brings back the latest reversal: turn 2's files.
    undo_backup.redo(tmp_path)
    assert _read(tmp_path, "a.txt") == "three\n"


def test_restore_stops_at_a_file_changed_since(tmp_path: Path) -> None:
    first, _second, _third = _three_turns(tmp_path)
    (tmp_path / "b.txt").write_text("the operator's edit\n", encoding="utf-8")

    results = undo_backup.restore(tmp_path, first.turn_id)

    # Turn 3 is reversed; turn 2 is reversed file by file, as /undo does, and
    # keeps b.txt, so the walk stops there: turn 1 is not reversed under it.
    assert [r.removed for r in results] == [["c.txt"], []]
    assert results[-1].skipped == ["b.txt"]
    assert _read(tmp_path, "b.txt") == "the operator's edit\n"
    assert _read(tmp_path, "a.txt") == "two\n"
    pending = [
        row["turn"]
        for row in undo_backup.checkpoints(tmp_path)
        if row["kind"] == "turn" and not row["done"]
    ]
    assert pending == [_second.turn_id, first.turn_id]


@pytest.mark.parametrize("bad", ["../escape", "", "no-such-turn", None, 3])
def test_restore_refuses_an_id_that_names_no_checkpoint(
    tmp_path: Path, bad: object
) -> None:
    _three_turns(tmp_path)
    with pytest.raises(ValueError):
        undo_backup.restore(tmp_path, bad)
    assert _read(tmp_path, "c.txt") == "made by turn 3\n"


def test_checkpoint_lists_them_numbered_newest_first(tmp_path: Path) -> None:
    _three_turns(tmp_path)
    text = _shown(tmp_path, "/checkpoint")
    assert text.index("1. ") < text.index("2. ") < text.index("3. ")
    assert "1 file: c.txt" in text and "2 files: a.txt, b.txt" in text
    assert "/restore N" in text


def test_restore_in_the_session(tmp_path: Path) -> None:
    _three_turns(tmp_path)
    text = _shown(tmp_path, "/restore 3")
    assert "removed c.txt" in text and "removed b.txt" in text
    assert "back at checkpoint 3" in text
    assert _read(tmp_path, "a.txt") == "two\n"


@pytest.mark.parametrize("args", ["", "0", "9", "x", "1 2", "-1"])
def test_restore_needs_one_listed_number(tmp_path: Path, args: str) -> None:
    _three_turns(tmp_path)
    text = _shown(tmp_path, f"/restore {args}".strip())
    assert "usage: /restore N" in text
    assert _read(tmp_path, "c.txt") == "made by turn 3\n"


def test_restore_1_changes_nothing(tmp_path: Path) -> None:
    _three_turns(tmp_path)
    assert "already as it left them" in _shown(tmp_path, "/restore 1")
    assert _read(tmp_path, "c.txt") == "made by turn 3\n"


def test_no_checkpoints_yet(tmp_path: Path) -> None:
    assert "no checkpoints yet" in _shown(tmp_path, "/checkpoint")
    assert "no checkpoints yet" in _shown(tmp_path, "/restore 2")


def test_both_fit_40_columns(tmp_path: Path, monkeypatch) -> None:
    _three_turns(tmp_path)
    _turn(tmp_path, {"src/a/very/long/path/name/module.py": "y\n"})
    monkeypatch.setattr(
        shutil,
        "get_terminal_size",
        lambda fallback=(80, 24): __import__("os").terminal_size((40, 24)),
    )
    for command in ("/checkpoint", "/restore 9", "/restore 3"):
        lines = _shown(tmp_path, command).splitlines()
        assert lines and all(len(line) <= 40 for line in lines), (command, lines)


def test_an_apply_keeps_its_base_snapshot_under_a_checkpoint_ref(
    tmp_path: Path, fake_model_server
) -> None:
    import subprocess

    from tests.test_session_turn import _repo
    from tests.test_step_tools_wired import _turn as _session_turn

    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_bytes().replace(b"\r\n", b"\n")

    code, _events = _session_turn(ws)
    assert code == 0

    refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname) %(objectname)",
            "refs/ract/checkpoints/",
        ],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    refs = [line.split() for line in refs if line]
    turn = undo_backup.checkpoints(ws)[0]["turn"]
    assert undo_backup.checkpoints(ws)[0]["request"] == "fix add"  # for /rewind
    assert [ref for ref, _sha in refs] == [f"refs/ract/checkpoints/{turn}/1"]
    base = subprocess.run(
        ["git", "show", f"{refs[0][1]}:src/calc.py"],
        cwd=ws,
        capture_output=True,
        check=True,
    ).stdout.replace(b"\r\n", b"\n")
    assert base == before  # the snapshot holds the file as it was before the turn

    # Pruning the turn's folder drops its refs too.
    undo_backup.prune(ws, keep=0)
    left = subprocess.run(
        ["git", "for-each-ref", "refs/ract/checkpoints/"],
        cwd=ws,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert left == ""


def _rewind(tmp_path: Path, answer: str) -> str:
    from tests.test_repl import _session

    session, _, console = _session(config=tmp_path / "ract.yaml")
    session._read_line = lambda _prompt: answer
    session.handle("/rewind")
    return console.text


def _turns_with_requests(root: Path) -> None:
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    for request, text in (
        ("make a say two", "two\n"),
        (f"key sk-{'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6'} three", "three\n"),
    ):
        with undo_backup.turn(root, request=request):
            undo_backup.save_before_replace(root, ["a.txt"])
            (root / "a.txt").write_text(text, encoding="utf-8")


def test_rewind_names_each_turn_by_its_request_and_goes_back(tmp_path: Path) -> None:
    _turns_with_requests(tmp_path)
    text = _rewind(tmp_path, "2")
    assert "1. " in text and "2. " in text and "make a say two" in text
    assert "a1B2c3D4e5F6" not in text  # a key in a request is masked
    assert "back at checkpoint 2" in text
    assert _read(tmp_path, "a.txt") == "two\n"


def test_rewind_with_enter_keeps_everything(tmp_path: Path) -> None:
    _turns_with_requests(tmp_path)
    assert "nothing rewound" in _rewind(tmp_path, "")
    assert _read(tmp_path, "a.txt") == "three\n"


def test_rewind_needs_two_turns(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")
    _turn(tmp_path, {"a.txt": "two\n"})
    assert "nothing to rewind to" in _rewind(tmp_path, "1")
