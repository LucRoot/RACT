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


def test_a_knot_that_does_not_verify_is_not_signed(ws: Path, monkeypatch) -> None:
    """G-226 note 1: signed comes from verification, not from a sidecar's presence."""
    import json

    from ract import session_turn

    original = session_turn._provenance

    def tampered(unsigned, changed, project):
        sidecar = project / "src" / ".calc.py.rootknot.json"
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["run_id"] = "someone-else"
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        return original(unsigned, changed, project)

    monkeypatch.setattr(session_turn, "_provenance", tampered)
    finished = _turn(ws)
    assert finished["provenance"]["signed"] is False
    assert finished["provenance"]["unverified_files"] == ["src/calc.py"]


@pytest.mark.parametrize(
    "auto, refuse_changes",
    [(True, False), (False, False)],
    ids=["default-repl-or-run-auto", "headless-accept-edits"],
)
def test_each_way_a_person_runs_it_signs(ws: Path, auto, refuse_changes) -> None:
    """G-226 note 2. ``ask`` is the /ask answer-only mode (no plan, nothing
    written), not the default: the default REPL and ``ract run --auto`` are
    auto=True, ``ract -p --accept-edits`` is auto=False with changes allowed."""
    events: list[SessionEvent] = []
    stream = EventStream(session="s-s015b-modes")
    stream.subscribe(events.append)
    request = TurnRequest(
        config=ws / "ract.yaml",
        intent="fix add in src/calc.py",
        session_id="s-s015b-modes",
        resume=False,
        auto=auto,
        refuse_changes=refuse_changes,
        terminal=auto,
    )
    import ract.approval_callback as ac

    original = ac.read_line
    ac.read_line = lambda _p: "y"
    try:
        assert run_turn(stream, request, turn=1, cancel=threading.Event()) == 0
    finally:
        ac.read_line = original
    ok, message = verify_artifact(ws / "src" / "calc.py", ws)
    assert ok, message


def test_the_snapshot_reads_at_most_its_total(tmp_path: Path, monkeypatch) -> None:
    """G-226 note 3: past the total, files are recorded by hash only."""
    import subprocess

    from ract import provenance_wiring

    monkeypatch.setattr(provenance_wiring, "_MAX_TOTAL_BYTES", 10)
    root = tmp_path / "p"
    root.mkdir()
    for name, text in (("a.txt", "12345678"), ("b.txt", "12345678")):
        (root / name).write_text(text, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    files = provenance_wiring._tracked_text(root)
    assert files["a.txt"] == "12345678" and files["b.txt"].startswith("sha256:")


def test_one_session_key_a_day_for_a_repository(ws: Path) -> None:
    """G-237 L4: a key per run left a busy user with thousands of key files."""
    from types import SimpleNamespace

    from ract import provenance_wiring
    from ract.core.keys import _default_state_dir

    keys = _default_state_dir() / "keys"
    before = set(keys.glob("*.pem")) if keys.is_dir() else set()
    for run in ("run-one", "run-two", "run-three"):
        executor = SimpleNamespace(install_v4_provenance_deps=lambda **_kw: None)
        assert provenance_wiring.install(executor, ws, "fix add", run_id=run) is None
    assert len(set(keys.glob("*.pem")) - before) <= 1  # the day's key, made once

    seed = provenance_wiring.session_seed
    assert seed(ws, "2026-10-30") == seed(ws, "2026-10-30")
    assert seed(ws, "2026-10-30") != seed(ws, "2026-10-31")
    assert seed(ws, "2026-10-30") != seed(ws.parent, "2026-10-30")
