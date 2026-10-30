"""B-014c, J5 in a real session: approve a fix, then reject it hunk by hunk with /review.

Runs the installed ``ract`` in a pseudo-terminal against the fake server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_session_turn import _repo
from tests.ux.terminal_driver import spawn


def _ract_exe() -> str:
    return str(
        Path(sys.executable).with_name("ract.exe" if os.name == "nt" else "ract")
    )


@pytest.mark.parametrize("cols", [80, 60, 40])
def test_review_rejects_the_fix_and_undo_stays_true(
    tmp_path: Path, fake_model_server: Any, cols: int
) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    before = (ws / "src" / "calc.py").read_text(encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    session = spawn([_ract_exe()], cwd=str(ws), env=env, cols=cols, rows=40)
    try:
        assert session.expect(r"\| default \|", 30)
        session.send_line("fix add")
        assert session.expect(r"\[y/N\]", 60)
        session.send_line("y")
        assert session.expect(r"/undo", 60)  # the turn summary's way back
        assert (ws / "src" / "calc.py").read_text(encoding="utf-8") != before
        session.send_line("/review")
        assert session.expect(r"Hunk 1 of 1 in src/calc\.py:", 30)
        assert session.expect(r"reject\s+the\s+rest\s+of\s+the\s+file:", 30)
        session.send_line("r")
        assert session.expect(
            r"src/calc\.py:\s+the\s+turn's\s+saved\s+copy\s+is\s+back", 30
        ), session.recording.plain[-3000:]
    finally:
        if session.alive():
            session.send_line("/exit")
        rec = session.close(timeout=15)
    assert (ws / "src" / "calc.py").read_text(encoding="utf-8") == before
    for line in rec.plain.splitlines():
        assert len(line) <= cols, line
