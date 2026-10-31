"""B-160d through the real entry point: `ract setup --answers` checks the overridden address.

A child process runs setup against a fake server on loopback that records every
request; RACT_NO_NETWORK keeps anything else unreachable, and PYTHONPATH pins the
child to this tree's code (G-255). The key is a throwaway value.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_KEY = "sk-throwaway-" + "R" * 32


class _Recorder(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, bool]] = []

    def do_POST(self) -> None:  # noqa: N802 - http.server name
        auth = self.headers.get("Authorization") or ""
        _Recorder.seen.append((self.path, FAKE_KEY in auth))
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = (
            b'{"choices": [{"message": {"content": "ready"}, "finish_reason": "stop"}]}'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


def _setup(tmp_path: Path, override: str, key_hosts: str) -> tuple[int, str, str]:
    server = http.server.HTTPServer(("127.0.0.1", 0), _Recorder)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    _Recorder.seen.clear()
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    answers = project / "answers.yaml"
    answers.write_text(
        "provider: cloud\ncloud:\n  preset: openai\ncheck: true\n", encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    env["OPENAI_API_KEY"] = FAKE_KEY
    env["RACT_NO_NETWORK"] = "1"
    env["RACT_PRESET_BASE_URL"] = override.format(port=port)
    if key_hosts:
        env["RACT_KEY_HOSTS"] = key_hosts.format(port=port)
    try:
        done = subprocess.run(
            [sys.executable, "-m", "ract.cli", "setup", "--answers", str(answers)],
            cwd=project,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    finally:
        server.shutdown()
    written = project / "ract.yaml"
    config = written.read_text(encoding="utf-8") if written.exists() else ""
    return done.returncode, done.stdout + done.stderr, config


@pytest.mark.parametrize("paired", [True, False])
def test_setup_checks_the_overridden_address(tmp_path: Path, paired: bool) -> None:
    code, output, config = _setup(
        tmp_path,
        "openai=http://127.0.0.1:{port}/v1",
        "OPENAI_API_KEY=127.0.0.1:{port}" if paired else "",
    )
    assert code == 0, output
    assert "ok: the model answered" in output
    assert [path for path, _ in _Recorder.seen] == ["/v1/chat/completions"]
    # The key goes to the overridden host only when the operator paired them.
    assert [carried for _, carried in _Recorder.seen] == [paired]
    assert FAKE_KEY not in output and FAKE_KEY not in config
    assert "127.0.0.1" in config


@pytest.mark.parametrize(
    "override",
    ["http://127.0.0.1:{port}/v1", "nosuch=http://127.0.0.1:{port}/v1", "openai=,"],
)
def test_a_malformed_override_refuses_setup_and_sends_nothing(
    tmp_path: Path, override: str
) -> None:
    # G-265: a bare URL, an unknown preset or an empty pair refuses (exit 2).
    code, output, config = _setup(tmp_path, override, "")
    assert code == 2, output
    assert "RACT_PRESET_BASE_URL must be preset=url" in output
    assert _Recorder.seen == [] and config == ""
