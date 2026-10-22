"""/sessions and /resume (B-032a): list saved sessions, switch to one, survive bad files."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from ract import cli
from ract.repl import ReplSession


class _Console:
    """Records output so tests can assert on what the operator would see."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args, **kwargs) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    info = success = warning = error = print

    def table(self, title, columns, rows) -> None:
        self.lines.append(title)
        self.lines.append(" | ".join(columns))
        for row in rows:
            self.lines.append(" | ".join(str(c) for c in row))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _session(tmp_path: Path):
    console = _Console()
    session = ReplSession(
        tmp_path / "ract.yaml",
        dispatch=lambda argv: 0,
        read_line=lambda prompt: "",
        console=console,
        verbs=cli.CLI_VERBS,
    )
    return session, console


def _store(tmp_path: Path) -> Path:
    directory = tmp_path / ".ract" / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write(directory: Path, session_id: str, intent: str, *, mtime: float) -> Path:
    path = directory / f"{session_id}.json"
    path.write_text(
        json.dumps({"intent": intent, "plan": {}, "artifacts": {}, "outcomes": []}),
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


def test_no_sessions_says_so_and_latest_changes_nothing(tmp_path):
    session, console = _session(tmp_path)
    before = session.state.session_id
    session.handle("/sessions")
    assert "no sessions yet" in console.text
    console.lines.clear()
    session.handle("/resume latest")
    assert "no sessions yet" in console.text
    assert session.state.session_id == before


def test_twelve_sessions_show_ten_newest_first(tmp_path):
    directory = _store(tmp_path)
    for i in range(12):
        _write(directory, f"s{i:02d}", f"request {i}", mtime=1_000_000 + i)
    session, console = _session(tmp_path)
    session.handle("/sessions")
    rows = [line for line in console.lines if line.startswith("s")]
    assert len(rows) == 10
    assert rows[0].startswith("s11")
    assert rows[-1].startswith("s02")
    assert "10 of 12 sessions" in console.text


def test_long_first_request_is_cut_to_fifty_characters_and_an_ellipsis(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "long-one", "x" * 10_000, mtime=1_000_000)
    session, console = _session(tmp_path)
    session.handle("/sessions")
    assert "x" * 50 + "..." in console.text
    assert "x" * 51 not in console.text


def test_escape_bytes_and_carriage_returns_in_a_request_render_inert(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "tricky", "hello\x1b[31m red\rback", mtime=1_000_000)
    session, console = _session(tmp_path)
    session.handle("/sessions")
    assert "\x1b" not in console.text
    assert "\r" not in console.text
    assert "hello" in console.text


def test_unreadable_files_get_a_row_and_the_rest_still_show(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "good", "a fine request", mtime=1_000_000)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    (directory / "typed.json").write_text(
        json.dumps({"intent": 7, "outcomes": []}), encoding="utf-8"
    )
    (directory / "huge.json").write_bytes(b" " * (2 * 1024 * 1024 + 1))
    session, console = _session(tmp_path)
    session.handle("/sessions")
    assert "a fine request" in console.text
    assert "unreadable" in console.text
    assert "too large" in console.text


def test_names_that_fail_require_name_are_skipped_and_never_read(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "good", "a fine request", mtime=1_000_000)
    hostile = directory / "..%2fx.json"
    hostile.write_text(json.dumps({"intent": "PWNED"}), encoding="utf-8")
    session, console = _session(tmp_path)
    session.handle("/sessions")
    assert "PWNED" not in console.text
    assert "1 of 1" not in console.text


def test_symlink_to_a_file_outside_the_store_is_never_read(tmp_path):
    directory = _store(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps({"intent": "SECRET"}), encoding="utf-8")
    try:
        os.symlink(outside, directory / "x.json")
    except (OSError, NotImplementedError):
        pytest.skip("creating symlinks needs privilege on this machine")
    session, console = _session(tmp_path)
    session.handle("/sessions")
    assert "SECRET" not in console.text
    before = session.state.session_id
    session.handle("/resume x")
    assert "SECRET" not in console.text
    assert session.state.session_id == before


def test_resume_switches_and_prints_a_one_line_summary(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "repl-20261022-100000", "fix the parser", mtime=1_000_000)
    session, console = _session(tmp_path)
    session.handle("/resume repl-20261022-100000")
    assert session.state.session_id == "repl-20261022-100000"
    assert session.state.session_started is True
    assert "resumed repl-20261022-100000" in console.text
    assert "last request: fix the parser" in console.text


def test_resume_latest_picks_the_newest_session(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "older", "first", mtime=1_000_000)
    _write(directory, "newer", "second", mtime=2_000_000)
    session, console = _session(tmp_path)
    session.handle("/resume latest")
    assert session.state.session_id == "newer"


def test_latest_skips_an_unreadable_newest_session(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "good", "readable", mtime=1_000_000)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    os.utime(directory / "broken.json", (2_000_000, 2_000_000))
    session, console = _session(tmp_path)
    session.handle("/resume latest")
    assert session.state.session_id == "good"
    assert "unreadable" not in console.text


def test_latest_says_so_when_nothing_is_readable(tmp_path):
    directory = _store(tmp_path)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    session, console = _session(tmp_path)
    before = session.state.session_id
    session.handle("/resume latest")
    assert "no readable session to resume" in console.text
    assert session.state.session_id == before


def test_unknown_id_gets_the_closest_match_as_a_hint(tmp_path):
    directory = _store(tmp_path)
    _write(directory, "repl-20261022-100000", "fix", mtime=1_000_000)
    session, console = _session(tmp_path)
    before = session.state.session_id
    session.handle("/resume repl-20261022-10000")
    assert "did you mean repl-20261022-100000" in console.text
    assert session.state.session_id == before


@pytest.mark.parametrize("target", ["../x", "..\\x", ".hidden"])
def test_hostile_ids_are_refused_plainly(tmp_path, target):
    session, console = _session(tmp_path)
    before = session.state.session_id
    assert session.handle(f"/resume {target}") is True
    assert "not a session id" in console.text
    assert session.state.session_id == before


def test_unreadable_session_is_not_resumed(tmp_path):
    directory = _store(tmp_path)
    (directory / "broken.json").write_text("{not json", encoding="utf-8")
    session, console = _session(tmp_path)
    before = session.state.session_id
    session.handle("/resume broken")
    assert "unreadable session: broken" in console.text
    assert session.state.session_id == before


def test_help_lists_both_commands(tmp_path):
    session, console = _session(tmp_path)
    session.handle("/help")
    assert "/sessions" in console.text
    assert "/resume" in console.text


def test_missing_resume_argument_prints_usage_and_changes_nothing(tmp_path):
    session, console = _session(tmp_path)
    before = session.state.session_id
    session.handle("/resume")
    assert "usage" in console.text.lower()
    assert session.state.session_id == before
