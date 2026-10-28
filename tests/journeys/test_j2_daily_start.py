"""J2 (UX_BAR): daily start in a configured repository.

The prompt's status line shows the model, the branch and the mode. The run is
a real `ract` in a pseudo-terminal against the fake model server.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

PROMPT = r"(ract|plan)> "


def test_the_status_line_names_the_model_the_branch_and_the_mode(
    tmp_path: Path,
) -> None:
    with FakeModelServer("j1_first_run") as server:
        ws = rb._workspace(tmp_path, "j2", git=True, files=rb.APP_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=ws,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        session = spawn([str(rb.RACT)], cwd=str(ws), env=rb._env(), cols=100, rows=40)
        try:
            assert session.expect(PROMPT, timeout=60), "no prompt at startup"
        finally:
            recording = session.close()
    status = recording.plain
    assert "fake-coder" in status, "the model is not on the status line"
    assert "default" in status, "the mode is not on the status line"
    assert branch and branch in status, (
        f"the branch {branch!r} is not on the status line"
    )
