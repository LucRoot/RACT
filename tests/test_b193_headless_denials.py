"""B-193: an approval nobody can answer in a headless run is a recorded denial.

``denials`` was always empty and ``--fail-on-denial`` was parsed and never
read. Repro on c191903: a step's tier-2 ``write_file AGENTS.md`` under
``-p --accept-edits`` was refused, exit 1, ``denials: []``, with and without
the flag. Now the refusal is emitted as ``approval.requested`` and
``approval.resolved`` (``by: unattended``), listed in ``denials``, and with
the flag the run stops there and exits 3. Fake model server; nothing runs.
"""

from __future__ import annotations

import io
import json
import threading
from pathlib import Path
from typing import Any

import pytest

from ract import turn_context
from ract.headless import denials, run_headless
from ract.session_events import EventStream, SessionEvent
from tests.test_step_tools_wired import _calls, _workspace

AGENTS = ("write_file", {"path": "AGENTS.md", "content": "be bold\n", "create": True})


def _headless(
    tmp_path: Path, fake_model_server: Any, monkeypatch, *flags: str, fmt: str = "json"
) -> tuple[int, str, Path]:
    ws = _workspace(tmp_path, fake_model_server, lambda _d: _calls(AGENTS))
    monkeypatch.chdir(ws)
    monkeypatch.setenv("RACT_NO_NETWORK", "1")
    out = io.StringIO()
    code = run_headless(
        ["-p", "--accept-edits", *flags, "make add add", "--output-format", fmt],
        stdin=io.StringIO(""),
        stdout=out,
        stderr=io.StringIO(),
    )
    return code, out.getvalue(), ws


def test_a_refused_tier_2_write_is_listed_in_denials(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    code, out, ws = _headless(tmp_path, fake_model_server, monkeypatch)
    result = json.loads(out)
    assert result["denials"] == [
        {"rule": "tier-2 write", "action": "write_file AGENTS.md", "tier": "T2"}
    ]
    assert code == result["exit_code"] != 3  # without the flag the run goes on
    assert not (ws / "AGENTS.md").exists()


def test_the_denial_is_emitted_as_requested_and_resolved_unattended(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    _code, out, _ws = _headless(
        tmp_path, fake_model_server, monkeypatch, fmt="stream-json"
    )
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    asked = [e for e in events if e.get("kind") == "approval.requested"]
    resolved = [e for e in events if e.get("kind") == "approval.resolved"]
    assert len(asked) == len(resolved) == 1
    assert asked[0]["data"]["tier"] == "T2"
    assert resolved[0]["data"] == {
        "id": asked[0]["data"]["id"],
        "choice": "denied",
        "by": "unattended",
    }


def test_fail_on_denial_stops_the_run_with_exit_3(
    tmp_path: Path, fake_model_server: Any, monkeypatch
) -> None:
    code, out, ws = _headless(tmp_path, fake_model_server, monkeypatch, "--fail-on-denial")
    result = json.loads(out)
    assert code == result["exit_code"] == 3
    assert result["error"]["kind"] == "refused"
    assert "write_file AGENTS.md" in result["error"]["message"]
    assert "--fail-on-denial" in result["error"]["message"]
    assert len(result["denials"]) == 1
    assert not (ws / "AGENTS.md").exists()


@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_record_denial_emits_both_events(tier: str) -> None:
    stream = EventStream(session="s-b193")
    seen: list[SessionEvent] = []
    stream.subscribe(seen.append)
    turn_context.bind(
        threading.Event(), lambda kind, data: stream.emit(kind, data, turn=1)
    )
    try:
        turn_context.record_denial(tier, "pytest -q\x1b[2J", rule="tests", reason="check")
    finally:
        turn_context.bind(None)
    assert [e.kind for e in seen] == ["approval.requested", "approval.resolved"]
    assert "\x1b" not in seen[0].data["action"]  # control characters escaped
    assert denials(seen) == [
        {"rule": "tests", "action": seen[0].data["action"], "tier": tier}
    ]
