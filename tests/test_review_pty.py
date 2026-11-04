"""B-014c, J5 in a real session: approve a fix, then reject it hunk by hunk with /review.

Runs the installed ``ract`` in a pseudo-terminal against the fake server.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from tests.test_session_turn import _repo
from tests.ux.terminal_driver import spawn
from tests.ux import run_baseline as rb


def _ract_exe() -> str:
    return str(rb.RACT)


@pytest.mark.parametrize("cols", [80, 60, 40])
def test_review_rejects_the_fix_and_undo_stays_true(
    tmp_path: Path, fake_model_server: Any, cols: int
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    # The test asserts the chrome prompt ("ract>"), which only renders
    # outside plain mode; pin TERM so an ambient TERM=dumb (Git Bash, some
    # CI shells) cannot flip the session into the "you:" plain labels.
    env["TERM"] = "xterm"
    session = spawn([_ract_exe()], cwd=str(ws), env=env, cols=cols, rows=40)
    try:
        # The status line folds between its items at 60 and 40 columns (J5 fix).
        assert session.expect(r"\| default", 30)
        session.send_line("fix add")
        assert session.expect(r"\[y/N\]", 60)
        session.send_line("y")
        assert session.expect(r"/undo", 60)  # the turn summary's way back
        assert (ws / "src" / "calc.py").read_text(encoding="utf-8") != before
        session.send_line("/review")
        assert session.expect(r"Hunk 1 of 1 in src/calc\.py:", 30)
        assert session.expect(r"answer:", 30)
        session.send_line("r")
        # The confirmation line wraps at 40 columns, and ConPTY's repaint can
        # repeat a character at the wrap in the rebuilt text; the prompt coming
        # back and the file's bytes are the facts this test checks.
        assert session.expect(r"ract>", 30), session.recording.plain[-3000:]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if (ws / "src" / "calc.py").read_text(encoding="utf-8") == before:
                break
            time.sleep(0.1)
    finally:
        if session.alive():
            session.send_line("/exit")
        session.close(timeout=15)
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == before
    # No width check here: the text rebuilt from ConPTY's output joins repainted
    # regions into long lines, so it is not the screen. The width rule is
    # checked on the session's console (test_review_hunks, 40 columns) and in
    # the J5 walks at 80, 60 and 40 columns (docs/ux/b014c).
