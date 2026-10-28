"""J6 (UX_BAR): interrupt and carry on.

Ctrl-C during a slow model reply returns to the prompt within two seconds,
the question stays in the transcript, and the next turn works. The run is a
real `ract` in a pseudo-terminal (tests/ux/terminal_driver.py) against the
fake model server. Waits are on observable events (the server has received
the request; the prompt is back), never on a fixed sleep.
"""

from __future__ import annotations

import time
from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

PROMPT = r"(ract|plan)> "
INTERRUPT_BUDGET_S = 2.0


def _wait_for_request(server: FakeModelServer, count: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if len(server.chat_requests) >= count:
            return True
        time.sleep(0.05)
    return False


def test_ctrl_c_during_a_slow_reply_returns_to_the_prompt_in_two_seconds(
    tmp_path: Path,
) -> None:
    with FakeModelServer("baseline_j6_today") as server:
        ws = rb._workspace(tmp_path, "j6", git=True, files=rb.APP_FILES)
        rb._configure(ws, server.base_url, "fake-slow")
        session = spawn([str(rb.RACT)], cwd=str(ws), env=rb._env(), cols=80, rows=40)
        try:
            assert session.expect(PROMPT, timeout=60), "no prompt at startup"
            session.send_line("explain this project")
            assert _wait_for_request(server, 1, timeout=60), (
                "the model never got the question"
            )
            t0 = session.ctrl_c()
            back = session.expect(PROMPT, timeout=INTERRUPT_BUDGET_S + 5)
            back_in = session.now() - t0
            assert back, "no prompt after Ctrl-C"
            assert back_in <= INTERRUPT_BUDGET_S, f"prompt back after {back_in:.2f} s"
            session.send_line("/settings")
            assert session.expect("settings|model|provider", timeout=30)
        finally:
            recording = session.close()
    assert "explain this project" in recording.plain
    assert "Traceback" not in recording.plain
