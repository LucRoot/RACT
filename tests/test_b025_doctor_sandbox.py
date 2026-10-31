"""B-025: `ract doctor --sandbox` per OS through a stubbed probe; the grant mismatch."""

from __future__ import annotations

import contextlib
import io
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from ract.cli import main as cli_main
from ract.cli import sandbox_report
from ract.security import command_sandbox

PASS = "throwaway passphrase for a test"


@pytest.fixture(autouse=True)
def fresh():
    command_sandbox._reset_for_tests()
    yield
    command_sandbox._reset_for_tests()


@pytest.mark.parametrize("system", ["Windows", "Darwin"])
def test_without_a_backend_it_says_best_effort(system: str) -> None:
    report = sandbox_report(system)
    assert report["tier3_commands"] == "best_effort" and report["why_not"]
    assert "files and network for tier-3 commands" in report["not_enforced"]
    assert "must say sandbox: best_effort" in report["grant"]


def test_linux_with_a_proved_backend_says_enforced(monkeypatch) -> None:
    class Fake:
        name = "linux-bwrap"

    monkeypatch.setattr(
        command_sandbox, "enforcing_backend", lambda system=None: (Fake(), "")
    )
    report = sandbox_report("Linux")
    assert report["tier3_commands"] == "enforced" and report["confines"]["files"]
    assert "process, memory and CPU limits" in report["not_enforced"]


def test_linux_whose_self_test_fails_says_why(monkeypatch) -> None:
    monkeypatch.setattr(
        command_sandbox,
        "enforcing_backend",
        lambda system=None: (None, "a network connection was not refused"),
    )
    report = sandbox_report("Linux")
    assert report["tier3_commands"] == "best_effort"
    assert report["why_not"] == "a network connection was not refused"


def test_the_command_prints_and_the_json_parses() -> None:
    for args in (["doctor", "--sandbox"], ["doctor", "--sandbox", "--json"]):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with contextlib.suppress(SystemExit):
                cli_main(args)
        out = buffer.getvalue()
        if "--json" in args:
            assert json.loads(out)["sandbox"]["platform"]
        else:
            assert out.startswith("platform: ") and "tier-3 commands: " in out


def test_a_grant_that_says_enforced_where_nothing_confines_does_not_hold(
    tmp_path, monkeypatch
) -> None:
    from ract.policy.grant import load_grant, sign
    from ract.policy.operator_key import generate, unlock

    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(
        command_sandbox, "enforcing_backend", lambda system=None: (None, "no backend")
    )
    key = generate(PASS)
    now = datetime.now(timezone.utc) - timedelta(hours=1)
    (tmp_path / ".ract").mkdir()
    (tmp_path / ".ract" / "policy.yaml").write_text(
        "version: 1\n"
        f"binding:\n  project_root: '{os.path.realpath(tmp_path)}'\n"
        f"issued_at: {now:%Y-%m-%dT%H:%M:%SZ}\n"
        f"expires_at: {now + timedelta(days=9):%Y-%m-%dT%H:%M:%SZ}\n"
        f"key_id: {key.key_id}\n"
        "sandbox: enforced\n",
        encoding="utf-8",
    )
    sign(tmp_path, unlock(PASS), key)
    state = load_grant(tmp_path)
    assert not state.holds and "best_effort" in state.reason
