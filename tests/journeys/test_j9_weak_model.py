"""J9 (UX_BAR): a weak or reasoning model.

Hidden reasoning from the model is neither shown on the screen nor sent back
to the model on the next request. The run is a real `ract` in a pseudo-terminal
against the fake model server.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

PROMPT = r"ract> "
HIDDEN = "I should not show this"


def test_hidden_reasoning_is_neither_shown_nor_sent_back(tmp_path: Path) -> None:
    with FakeModelServer("baseline_j9_today") as server:
        ws = rb._workspace(tmp_path, "j9", git=True, files=rb.CALC_FILES)
        rb._configure(ws, server.base_url, "fake-weak")
        session = spawn([str(rb.RACT)], cwd=str(ws), env=rb._env(), cols=80, rows=40)
        try:
            assert session.expect(PROMPT, timeout=60), "no prompt at startup"
            for _ in range(2):
                session.send_line("summarize the README")
                assert session.expect(PROMPT, timeout=120), "a turn got no answer"
            session.send_line("/exit")
        finally:
            recording = session.close()
    assert len(server.chat_requests) >= 2
    sent_back = any(HIDDEN in str(r.body) for r in server.chat_requests)
    assert not sent_back, "hidden reasoning was sent back to the model"
    assert HIDDEN not in recording.plain, "hidden reasoning reached the screen"
    assert "Traceback" not in recording.plain
