"""S-008: `ract doctor` reports sandbox enforcement from facts.

The Linux and macOS backends render commands and never run them, so no
platform enforces filesystem, network or process limits in this build. The
report must say so on every platform, start no process, and change only when
a backend's entry in ``_BACKEND_EXECUTES`` changes in the commit that makes it
execute.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract import doctor
from tests.ux import run_baseline as rb


@pytest.mark.parametrize(
    "system, backend, binary",
    [
        ("Linux", "linux-bwrap", "bwrap"),
        ("Darwin", "macos-sandbox-exec", "sandbox-exec"),
        ("Windows", "none", None),
    ],
)
def test_no_platform_enforces_in_this_build(
    monkeypatch: pytest.MonkeyPatch, system: str, backend: str, binary: str | None
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: pytest.fail("sandbox_status must not start a process"),
    )
    status = doctor.sandbox_status(system)
    assert status.backend == backend
    assert status.executes_commands is False
    for prop in ("filesystem", "network", "process limits"):
        assert status.properties[prop] == "not enforced in this build"
    if binary:
        assert status.backend_binary == f"/usr/bin/{binary}"


def test_a_backend_marked_executing_reports_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setitem(doctor._BACKEND_EXECUTES, "linux-bwrap", True)
    status = doctor.sandbox_status("Linux")
    assert status.executes_commands is True
    assert status.properties["filesystem"] == "enforced"


def test_missing_binary_never_reports_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setitem(doctor._BACKEND_EXECUTES, "linux-bwrap", True)
    assert doctor.sandbox_status("Linux").executes_commands is False


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


def test_doctor_prints_and_emits_the_sandbox_facts(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    rb._configure(ws, "http://127.0.0.1:9/v1", "fake-coder")

    text = _doctor(ws).stdout
    assert "no backend runs commands in this build" in text
    assert "filesystem: not enforced in this build" in text

    data = json.loads(_doctor(ws, "--json").stdout)
    assert data["sandbox"]["executes_commands"] is False
    assert data["sandbox"]["properties"]["network"] == "not enforced in this build"


@pytest.mark.parametrize("system", ["Linux", "Darwin", "Windows"])
def test_environment_line_says_what_inherits(
    monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    """AUD-007: only hook commands are scrubbed on the `ract run` path; the
    report said every spawn on the substrate path was, on every platform."""
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    env = doctor.sandbox_status(system).properties["environment"]
    assert env == (
        "scrubbed by allowlist for hook commands; inherited from your shell "
        "for test, lint and step commands"
    )


def test_environment_line_changes_only_with_both_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setitem(doctor._BACKEND_EXECUTES, "linux-bwrap", True)
    assert "inherited" in doctor.sandbox_status("Linux").properties["environment"]
    monkeypatch.setattr(doctor, "_RUN_PATH_SCRUBS_STEP_ENV", True)
    assert doctor.sandbox_status("Linux").properties["environment"] == (
        "scrubbed by allowlist for every command RACT starts"
    )
