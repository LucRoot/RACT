"""B-041b: plain mode for screen readers and dumb terminals.

``--plain`` or ``TERM=dumb`` gives output a screen reader or a log reads in
order: no box drawing, no color, no cursor movement, and labels on each
speaker's lines. Child processes, so the console is built the way a user's
shell builds it.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ract.session_events import EventStream
from ract.session_render import PlainRenderer

ESC = "\x1b"
BELL = "\x07"
BOX_CHARS = "╭╮╰╯│─┏┓┗┛┃━┣┫┳┻╋"
MAIN = "import sys; from ract.cli import main; sys.exit(main(sys.argv[1:]))"


def _child(cwd: Path, args: list[str], code: str | None = None, **env: str) -> str:
    base = {
        key: value
        for key, value in os.environ.items()
        if key not in {"NO_COLOR", "FORCE_COLOR", "TERM"}
    }
    base.update(env)
    command = [sys.executable, "-c", code or MAIN, *args]
    proc = subprocess.run(
        command,
        cwd=cwd,
        env=base,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        input="/exit\n" if code else None,
        timeout=180,
        check=False,
    )
    return proc.stdout + proc.stderr


def _renderer(
    *, labels: bool = False
) -> tuple[EventStream, io.StringIO, PlainRenderer]:
    out = io.StringIO()
    stream = EventStream(
        session="s-1",
        clock=lambda: datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc),
    )
    renderer = PlainRenderer(out.write, labels=labels)
    stream.subscribe(renderer)
    return stream, out, renderer


def test_plain_flag_removes_escapes_and_box_characters(tmp_path: Path) -> None:
    out = _child(tmp_path, ["--plain", "doctor"], FORCE_COLOR="1")
    assert ESC not in out
    assert not any(char in out for char in BOX_CHARS)


def test_term_dumb_gives_the_same_output_as_plain(tmp_path: Path) -> None:
    plain = _child(tmp_path, ["--plain", "doctor"])
    dumb = _child(tmp_path, ["doctor"], TERM="dumb")
    assert dumb == plain


def test_plain_repl_banner_draws_no_boxes(tmp_path: Path) -> None:
    code = (
        "from pathlib import Path\n"
        "from ract.repl import ReplSession\n"
        "ReplSession(Path('ract.yaml')).run()\n"
    )
    out = _child(tmp_path, [], code=code, TERM="dumb")
    assert ESC not in out
    assert not any(char in out for char in BOX_CHARS)


def test_plain_answer_has_one_label_and_indented_continuation() -> None:
    stream, out, renderer = _renderer(labels=True)
    stream.emit("turn.started", {}, turn=1)
    stream.emit("agent.text.delta", {"text": "Hello\nsecond line"}, turn=1)
    renderer.close()
    text = out.getvalue()
    assert text.count("ract: ") == 1
    assert "ract: Hello\n  second line" in text


def test_plain_error_has_the_error_label() -> None:
    stream, out, renderer = _renderer(labels=True)
    stream.emit(
        "error.surfaced",
        {"message": "the model timed out", "hint": "run ract doctor"},
        turn=1,
    )
    renderer.close()
    assert "error: the model timed out" in out.getvalue()


def test_labels_are_off_by_default() -> None:
    stream, out, renderer = _renderer()
    stream.emit("agent.text.delta", {"text": "Hello"}, turn=1)
    renderer.close()
    assert "ract:" not in out.getvalue()
    assert "Hello" in out.getvalue()


def test_plain_output_never_rewrites_a_line_with_a_carriage_return() -> None:
    stream, out, renderer = _renderer(labels=True)
    stream.emit("agent.text.delta", {"text": "one\r\ntwo\rthree"}, turn=1)
    renderer.close()
    assert "\r" not in out.getvalue()


def test_hostile_answer_text_loses_its_escape_and_bell() -> None:
    stream, out, renderer = _renderer(labels=True)
    stream.emit("agent.text.delta", {"text": f"ok{ESC}[2J{BELL} end"}, turn=1)
    renderer.close()
    text = out.getvalue()
    assert ESC not in text
    assert BELL not in text
    assert "ok" in text and "end" in text
