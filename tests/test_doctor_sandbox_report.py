"""S-008 + G3-P1: `ract doctor` reports sandbox enforcement from facts.

The tier-3 confinement fact comes from the live self-test
(``security.command_sandbox.enforcing_backend``), the same source as
``ract doctor --sandbox`` and ``/permissions``; the three screens must
agree on every machine. This host cannot run bwrap, so these tests mock
the self-test result both ways: a passing self-test means enforced, a
failing or absent one means best effort.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ract import doctor
from ract.security import command_sandbox
from tests.ux import run_baseline as rb


class _FakeBackend:
    name = "linux-bwrap"


def _mock_self_test(monkeypatch: pytest.MonkeyPatch, *, confined: bool) -> None:
    """Pretend the live self-test proved confinement, or proved nothing."""
    backend = _FakeBackend() if confined else None
    why = "" if confined else "a write into a read-only system folder was not refused"
    monkeypatch.setattr(
        command_sandbox,
        "enforcing_backend",
        lambda system=None: (backend, why),
    )


def _doctor_posture(status: doctor.SandboxStatus):
    """The posture screen line ``_doctor`` in cli.py builds from the facts."""
    from ract.ui import posture_screens as ps

    found = (
        status.backend
        if status.backend_binary
        else (
            f"no backend for {status.platform}"
            if status.backend == "none"
            else f"{status.backend} not found on PATH"
        )
    )
    posture = ps.SandboxPosture(
        backend=found,
        posture=ps.ENFORCED if status.executes_commands else ps.BEST_EFFORT,
    )
    return posture, ps.sandbox_line(posture), ps.doctor_sandbox_lines(posture, 80)


@pytest.mark.parametrize(
    "system, backend, binary",
    [
        ("Linux", "linux-bwrap", "bwrap"),
        ("Darwin", "macos-sandbox-exec", "sandbox-exec"),
        ("Windows", "none", None),
    ],
)
def test_no_machine_confines_until_its_self_test_proves_it(
    monkeypatch: pytest.MonkeyPatch, system: str, backend: str, binary: str | None
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    _mock_self_test(monkeypatch, confined=False)
    status = doctor.sandbox_status(system)
    assert status.backend == backend
    assert status.executes_commands is False
    for prop in ("filesystem", "network", "process limits"):
        assert status.properties[prop] == "not enforced in this build"
    if binary:
        assert status.backend_binary == f"/usr/bin/{binary}"


def test_a_proved_backend_reports_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    _mock_self_test(monkeypatch, confined=True)
    status = doctor.sandbox_status("Linux")
    assert status.executes_commands is True
    assert status.properties["filesystem"] == "enforced"
    assert status.properties["network"] == "enforced"
    # The bwrap render applies no rlimits: process limits stay honest even
    # where the self-test passed (the --sandbox screen agrees).
    assert status.properties["process limits"] == "not enforced in this build"


def test_a_failing_self_test_never_reports_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    _mock_self_test(monkeypatch, confined=False)
    assert doctor.sandbox_status("Linux").executes_commands is False


@pytest.mark.parametrize("confined", [True, False], ids=["enforced", "best_effort"])
def test_doctor_agrees_with_sandbox_report_and_permissions(
    monkeypatch: pytest.MonkeyPatch, confined: bool
) -> None:
    """G3-P1 lock: under one self-test result, all three surfaces say the same.

    ``ract doctor``'s posture (facts via ``sandbox_status``), ``ract doctor
    --sandbox`` (``sandbox_report``) and ``/permissions``
    (``sandbox_confines_commands``) must agree on every machine.
    """
    _mock_self_test(monkeypatch, confined=confined)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    from ract.cli import sandbox_report
    from ract.policy.grant import sandbox_confines_commands

    status = doctor.sandbox_status("Linux")
    assert status.executes_commands is confined
    assert status.executes_commands == sandbox_confines_commands()
    assert (sandbox_report("Linux")["tier3_commands"] == "enforced") is confined

    posture, line, lines = _doctor_posture(status)
    if confined:
        assert line == "sandbox: enforced on this machine (linux-bwrap)"
    else:
        assert (
            line == "sandbox: best effort, not enforced on this machine (linux-bwrap)"
        )
    # The naming and the advice sentence follow the same fact.
    assert posture.backend == "linux-bwrap"
    text = "\n".join(lines)
    assert ("a grant must say sandbox: best_effort" in text) is not confined
    if confined:
        assert "does not confine commands" not in text
    else:
        assert "this machine does not confine commands" in text


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
    # B-225: the posture screen; this machine confines nothing, so best effort.
    assert "sandbox: best effort, not enforced on this machine" in text
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
    _mock_self_test(monkeypatch, confined=False)
    env = doctor.sandbox_status(system).properties["environment"]
    assert env == (
        "scrubbed by allowlist for hook commands; inherited from your shell "
        "for test, lint and step commands"
    )


def test_environment_line_changes_only_with_both_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    _mock_self_test(monkeypatch, confined=True)
    assert "inherited" in doctor.sandbox_status("Linux").properties["environment"]
    monkeypatch.setattr(doctor, "_RUN_PATH_SCRUBS_STEP_ENV", True)
    assert doctor.sandbox_status("Linux").properties["environment"] == (
        "scrubbed by allowlist for every command RACT starts"
    )
