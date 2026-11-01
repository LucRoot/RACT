"""B-219: every README and QUICKSTART command example that needs no model
runs, and the outcome the document promises is what happens.

These are the promises the documents make about refusals and exits; each
test runs the real CLI in a temporary workspace with no provider, so no
model is needed and nothing leaves the machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ract(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def test_loop_refuses_without_yolo_as_QUICKSTART_says(tmp_path: Path) -> None:
    """QUICKSTART: `--loop` refuses to run without `--yolo`."""
    (tmp_path / "ract.yaml").write_text("project:\n  name: demo\n", encoding="utf-8")
    proc = _ract(tmp_path, "run", "fix something", "--loop")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "--yolo" in proc.stdout + proc.stderr


def test_a_run_with_no_terminal_refuses_to_change_files(
    tmp_path: Path, fake_model_server
) -> None:
    """QUICKSTART: with no terminal to ask, a run without --yolo or
    --accept-edits does not change files (exit 3)."""
    from tests.fixtures.fake_model_server import Scenario
    from tests.test_session_turn import _repo

    server = fake_model_server(
        Scenario.from_dict(
            {
                "turns": [
                    {
                        "reply": {
                            "kind": "text",
                            "content": '{"assumption": "a", "confidence": 0.9, "steps": [{"action": "change a file", "provider_hint": "local", "expected_artifact": "a.txt"}]}',
                        }
                    }
                ]
            }
        )
    )
    ws = _repo(tmp_path, server.base_url)
    proc = _ract(ws, "-p", "fix something")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "--accept-edits" in proc.stdout + proc.stderr
    assert not (ws / "a.txt").exists()


def test_memory_verify_consistency_on_a_fresh_repo_is_unavailable(
    tmp_path: Path,
) -> None:
    """The command's help: exit 2 when the backing store is missing."""
    proc = _ract(tmp_path, "memory", "verify-consistency")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "UNAVAILABLE" in proc.stdout + proc.stderr


def test_trace_help_names_no_writer(tmp_path: Path) -> None:
    """README and the verb index: no shipped command writes an event log."""
    proc = _ract(tmp_path, "trace", "--help")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No shipped command writes one" in proc.stdout
