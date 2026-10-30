"""S-015b: the harness signs what it writes; `ract provenance verify` passes.

Real turns on the fake model server (the J4 scenario rewrites src/calc.py).
The session, sandbox and ALM keys are made in the test's own state folder
(conftest isolates LOCALAPPDATA and XDG_STATE_HOME); never the operator's.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from ract.provenance_cli import verify_artifact
from ract.session_events import EventStream, SessionEvent
from ract.session_turn import TurnRequest, run_turn
from tests.test_session_turn import _repo


@pytest.fixture
def ws(tmp_path: Path, fake_model_server) -> Path:
    server = fake_model_server("baseline_j4_today")
    return _repo(tmp_path, server.base_url)


def _turn(ws: Path) -> dict:
    events: list[SessionEvent] = []
    stream = EventStream(session="s-s015b")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add in src/calc.py",
        session_id="s-s015b",
        resume=False,
        auto=False,
    )
    code = run_turn(stream, request, turn=1, cancel=threading.Event())
    assert code == 0, [e.data for e in events if e.kind == "error.surfaced"]
    return events[-1].data


def test_a_run_then_verify_passes(ws: Path) -> None:
    finished = _turn(ws)
    assert finished["changed"] == ["src/calc.py"]
    target = ws / "src" / "calc.py"
    assert (ws / "src" / ".calc.py.rootknot.json").is_file()
    ok, message = verify_artifact(target, ws)
    assert ok, message
    # B-038/B-039: a signed file is not listed as unsigned, and the turn says signed.
    assert finished["provenance"] == {"signed": True, "unsigned_files": []}


def test_one_changed_byte_fails_verification(ws: Path) -> None:
    _turn(ws)
    target = ws / "src" / "calc.py"
    data = bytearray(target.read_bytes())
    data[0] ^= 0x01
    target.write_bytes(bytes(data))
    ok, _message = verify_artifact(target, ws)
    assert not ok


def test_when_signing_cannot_be_built_the_file_is_honestly_unsigned(
    ws: Path, monkeypatch, capsys
) -> None:
    import ract.core.keys as keys

    def refuse(*_a, **_kw):
        raise OSError("no state folder")

    monkeypatch.setattr(
        keys.SessionKey, "load_or_create", classmethod(lambda cls, *a, **k: refuse())
    )
    finished = _turn(ws)
    assert "signing is off for this run" in capsys.readouterr().out
    assert not (ws / "src" / ".calc.py.rootknot.json").exists()
    assert "src/calc.py" in (finished.get("provenance") or {}).get("unsigned_files", [])
    ok, message = verify_artifact(ws / "src" / "calc.py", ws)
    assert not ok and "no Rootknot was recorded" in message


def test_the_run_keys_live_outside_the_project_and_are_archived(ws: Path) -> None:
    from ract.key_paths import repo_key_dir

    _turn(ws)
    for kind in ("sandbox", "alm"):
        live = repo_key_dir(ws, kind)
        assert list((live / "archive").glob("*.key")), kind
        assert not list(live.glob("*.key")), kind  # archived at once
    assert not list((ws / ".ract").rglob("*.key"))


def test_every_knot_is_v4(ws: Path) -> None:
    import json

    _turn(ws)
    data = json.loads(
        (ws / "src" / ".calc.py.rootknot.json").read_text(encoding="utf-8")
    )
    assert data["schema"] == "sidecar/v4" and data["schema_version"] == 4
