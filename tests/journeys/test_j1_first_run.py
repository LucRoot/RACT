"""J1 (UX_BAR): first run in an empty directory, no config.

RACT offers setup, asks at most four questions, writes ract.yaml, and ends at
a working prompt that answers a first question. The run is a real `ract` in a
pseudo-terminal against the fake model server, reached through RACT_BASE_URL.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.fake_model_server import FakeModelServer
from tests.journeys._j1_setup import setup_scenario
from tests.ux import run_baseline as rb
from tests.ux.terminal_driver import spawn

SETUP_OFFER = r"Set one up now\?"


def test_first_run_in_an_empty_folder_writes_a_config_and_answers(
    tmp_path: Path,
) -> None:
    with FakeModelServer(setup_scenario()) as server:
        ws = rb._workspace(tmp_path, "j1", git=False)
        env = {**rb._env(), "RACT_BASE_URL": server.base_url}
        session = spawn([str(rb.RACT)], cwd=str(ws), env=env, cols=80, rows=40)
        try:
            asked = 0
            assert session.expect(SETUP_OFFER, timeout=60), "no setup offer"
            asked += 1
            session.send_line("")  # set one up now? yes
            assert session.expect(r"Use the server at", timeout=60)
            asked += 1
            session.send_line("")  # use it? yes
            assert session.expect(r"Run git init here now", timeout=60)
            asked += 1
            session.send_line("y")
            assert session.expect(r"ract> ", timeout=120), "no working prompt"
            session.send_line("what does this folder contain?")
            answered = session.expect(r"Done: ", timeout=120)
        finally:
            recording = session.close()
    assert asked == 3, f"setup asked {asked} questions"
    assert asked <= 4, "J1 allows at most four questions"
    assert (ws / "ract.yaml").is_file(), "no config was written"
    assert answered, "the first question got no answer"
    assert "Traceback" not in recording.plain
