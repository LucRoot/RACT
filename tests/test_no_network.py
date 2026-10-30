"""V7-06 (D-115): --no-network and RACT_NO_NETWORK refuse every non-loopback request.

Hostile first: a provider on another host is refused before any connection,
with exit 3, a sentence naming the purpose and the host, and a ledger record;
a project's ract.yaml cannot lift the switch. Then: a loopback model server
still works, the loopback rule is strict (no LAN address), and doctor shows it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from ract import egress_ledger
from tests.test_session_turn import _repo


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RACT_")}
    env["RACT_EGRESS_LEDGER"] = str(tmp_path / "egress.jsonl")
    env.update(extra)
    return env


def _ract(
    ws: Path, env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ract.cli", *args],
        cwd=ws,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=240,
    )


def _ledger(tmp_path: Path) -> list[dict[str, Any]]:
    return egress_ledger.read(tmp_path / "egress.jsonl")


# --- hostile cases ----------------------------------------------------------


def test_no_network_refuses_a_non_loopback_provider_before_any_connection(
    tmp_path: Path,
) -> None:
    ws = _repo(tmp_path, "http://models.example.invalid/v1")
    result = _ract(
        ws,
        _env(tmp_path),
        "-p",
        "--no-network",
        "--accept-edits",
        "--trust-project",  # S-025: an untrusted project never loads a network provider
        "fix add",
        "--output-format",
        "json",
    )
    assert result.returncode == 3, result.stderr
    assert (
        "refused: --no-network is on and plan would connect to models.example.invalid"
        in result.stderr
    )
    records = _ledger(tmp_path)
    assert records and all(r["status"] == "refused_no_network" for r in records), (
        records
    )
    assert all(r["bytes_in"] == 0 for r in records)


def test_the_transport_is_never_reached_when_the_switch_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(egress_ledger, "_no_network", True)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={})

    with egress_ledger.client(
        "model", transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(egress_ledger.NetworkRefused):
            client.get("https://api.example.invalid/v1/models")
        assert client.get("http://127.0.0.1:9/v1/models").status_code == 200
    assert calls == ["http://127.0.0.1:9/v1/models"]


def test_no_network_cannot_be_lifted_by_project_config(tmp_path: Path) -> None:
    ws = _repo(tmp_path, "http://models.example.invalid/v1")
    config = ws / "ract.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "\nno_network: false\nnetwork: allowed\n",
        encoding="utf-8",
    )
    result = _ract(
        ws,
        _env(tmp_path, RACT_NO_NETWORK="1"),
        "-p",
        "--accept-edits",
        "--trust-project",  # S-025: an untrusted project never loads a network provider
        "fix add",
        "--output-format",
        "json",
    )
    assert result.returncode == 3, result.stderr
    assert "refused: RACT_NO_NETWORK is on" in result.stderr


# --- what still works and the rules ----------------------------------------


def test_no_network_allows_loopback(tmp_path: Path, fake_model_server: Any) -> None:
    server = fake_model_server("baseline_j4_today")
    ws = _repo(tmp_path, server.base_url)
    result = _ract(
        ws,
        _env(tmp_path),
        "-p",
        "--no-network",
        "--accept-edits",
        "--trust-project",  # S-025: an untrusted project never loads a network provider
        "fix add",
        "--output-format",
        "json",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["outcome"] == "done"


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("localhost", True),
        ("LOCALHOST", True),
        ("127.0.0.1", True),
        ("127.5.5.5", True),
        ("::1", True),
        ("[::1]", True),
        ("192.168.1.5", False),
        ("10.0.0.1", False),
        ("0.0.0.0", False),
        ("api.example.com", False),
        ("", False),
        (None, False),
    ],
)
def test_loopback_is_strict(host: str | None, loopback: bool) -> None:
    assert egress_ledger.is_loopback(host) is loopback


@pytest.mark.parametrize(
    ("value", "on"),
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("enabled", True),
        ("2", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
        ("", False),
        ("  ", False),
    ],
)
def test_the_variable_fails_tight(
    monkeypatch: pytest.MonkeyPatch, value: str, on: bool
) -> None:
    # G-198: any non-empty value turns it on, except an explicit off word.
    monkeypatch.setattr(egress_ledger, "_no_network", False)
    monkeypatch.setenv("RACT_NO_NETWORK", value)
    assert (egress_ledger.network_off() == "RACT_NO_NETWORK") is on


def test_ract_run_and_a_session_turn_exit_3_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # G-198 (a): the refusal is exit 3 on every entry point, not only -p.
    import threading

    from ract.session_turn import run_turn
    from tests.test_session_turn import _collect, _request

    ws = _repo(tmp_path, "http://models.example.invalid/v1")
    env = _env(tmp_path)
    # `ract run` has no --trust-project: trust the project as a user does (the
    # trust store is in the test session's own state directory).
    assert _ract(ws, env, "trust").returncode == 0
    run = _ract(ws, env, "run", "--no-network", "--yolo", "fix add")
    assert run.returncode == 3, run.stdout + run.stderr
    monkeypatch.setattr(egress_ledger, "_no_network", True)
    monkeypatch.setattr("ract.trust.is_trusted", lambda *a, **k: True)
    stream, events = _collect()
    code = run_turn(stream, _request(ws), turn=1, cancel=threading.Event())
    assert code == 3, [e.data for e in events if e.kind == "error.surfaced"]


def test_doctor_egress_shows_the_switch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    off = _ract(ws, _env(tmp_path), "doctor", "--egress")
    on = _ract(ws, _env(tmp_path, RACT_NO_NETWORK="1"), "doctor", "--egress")
    assert "network: allowed" in off.stdout, off.stdout + off.stderr
    assert "network: loopback only (RACT_NO_NETWORK=1)" in on.stdout, (
        on.stdout + on.stderr
    )


def test_the_flag_is_in_run_and_print_help(tmp_path: Path) -> None:
    for argv in (["run", "--help"], ["-p", "--help"]):
        text = _ract(tmp_path, _env(tmp_path), *argv).stdout
        assert "--no-network" in text and "localhost still works" in " ".join(
            text.split()
        ), argv


def test_a_wrapped_refusal_is_still_recognized() -> None:
    wrapped = (
        "Planning failed: Provider call failed: refused: --no-network is on and "
        "plan would connect to api.example.com. hint: use a model server"
    )
    assert egress_ledger.is_network_refusal(wrapped)
    assert not egress_ledger.is_network_refusal("refused: a path outside the project")
    assert not egress_ledger.is_network_refusal(None)
