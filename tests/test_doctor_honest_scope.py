"""S-012: `ract doctor` says what it checked.

The UX baseline (J1b) followed the printed first-run hint, got a config for a
server that was not running, and `ract doctor` reported 7/7 checks passed.
The doctor still contacts no provider by default (it stays fast and safe for
CI), but it now says so and names the command that does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tests.ux import run_baseline as rb


def _doctor(ws: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["NO_COLOR"] = "1"
    env["COLUMNS"] = "120"
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", "doctor", "--config", "ract.yaml", *args],
        cwd=ws,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )


def _ws(tmp_path: Path, url: str) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, url, "fake-coder")
    return ws


def test_default_doctor_says_providers_were_not_contacted(tmp_path: Path) -> None:
    ws = _ws(tmp_path, "http://127.0.0.1:9/v1")
    result = _doctor(ws)
    assert result.returncode == 0
    assert "config checks passed" in result.stdout
    assert "Providers were not contacted" in result.stdout
    assert "ract doctor --check-providers" in result.stdout


def test_check_providers_fails_for_a_server_that_is_not_running(tmp_path: Path) -> None:
    ws = _ws(tmp_path, "http://127.0.0.1:9/v1")
    result = _doctor(ws, "--check-providers")
    assert result.returncode == 1
    assert "not contacted" not in result.stdout
    assert "FAIL" in result.stdout


def test_check_providers_passes_for_a_running_server(
    tmp_path: Path, fake_model_server: Any
) -> None:
    server = fake_model_server("j1_first_run")
    ws = _ws(tmp_path, server.base_url)
    result = _doctor(ws, "--check-providers")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "checks passed" in result.stdout
    assert "config checks passed" not in result.stdout


def test_json_output_states_whether_providers_were_contacted(tmp_path: Path) -> None:
    import json

    ws = _ws(tmp_path, "http://127.0.0.1:9/v1")
    data = json.loads(_doctor(ws, "--json").stdout)
    assert data["providers_contacted"] is False


def test_init_provider_hint_points_at_the_provider_check(tmp_path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "--init-provider", "local"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=env,
    )
    assert result.returncode == 0
    assert "ract doctor --check-providers" in result.stdout
