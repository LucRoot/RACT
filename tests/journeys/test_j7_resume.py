"""J7 (UX_BAR): resume an earlier session.

A session made in one terminal is listed by `/sessions` in a new terminal, and
`/resume` brings its transcript back. The fake model server answers both runs;
each wait is on the prompt coming back, not on a fixed time.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

PROMPT = r"ract> "
QUESTION = "where is the config loader and who calls it?"


def test_an_earlier_session_is_listed_and_resumed_from_a_new_terminal(
    tmp_path: Path,
) -> None:
    with FakeModelServer("baseline_j3_today") as server:
        ws = rb._workspace(tmp_path, "j7", git=True, files=rb.APP_FILES)
        rb._configure(ws, server.base_url, "fake-coder")
        env = rb._env()

        first = spawn([str(rb.RACT)], cwd=str(ws), env=env, cols=80, rows=40)
        try:
            assert first.expect(PROMPT, timeout=60), "no prompt in the first terminal"
            first.send_line(QUESTION)
            assert first.expect(PROMPT, timeout=120), "the first question got no answer"
            first.send_line("/exit")
        finally:
            first.close()

        second = spawn([str(rb.RACT)], cwd=str(ws), env=env, cols=80, rows=40)
        try:
            assert second.expect(PROMPT, timeout=60), "no prompt in the new terminal"
            second.send_line("/sessions")
            assert second.expect(r"repl-\d{8}-\d{6}", timeout=60), (
                "the earlier session is not listed"
            )
            second.send_line("/resume")
            assert second.expect(r"resum", timeout=60), "/resume did not resume"
            second.send_line("/exit")
        finally:
            recording = second.close()
    assert "Traceback" not in recording.plain
