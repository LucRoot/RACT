"""Tests for the ract handshakes --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys
from pathlib import Path


def test_cli_handshakes_list_json_shows_added_item(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    registry_dir = tmp_path / ".ract"
    registry_dir.mkdir()
    registry_dir.joinpath("handshakes.json").write_text(
        json.dumps(
            [
                {
                    "id": "m1",
                    "description": "deploy",
                    "acceptance": "ok",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "status": "pending",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "handshakes",
            "list",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    items = json.loads(result.stdout)
    assert any(item["id"] == "m1" for item in items)


def test_cli_handshakes_approve_json_reports_status(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    registry_dir = tmp_path / ".ract"
    registry_dir.mkdir()
    registry_dir.joinpath("handshakes.json").write_text(
        json.dumps(
            [
                {
                    "id": "m1",
                    "description": "deploy",
                    "acceptance": "ok",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "status": "pending",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "handshakes",
            "approve",
            "m1",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # B-111 (R2): approving outside a session needs the operator key unlocked
    # at a terminal; with no terminal (and no key) nothing is approved.
    assert result.returncode == 3, result.stderr
    assert "operator key" in result.stderr
    stored = json.loads(
        registry_dir.joinpath("handshakes.json").read_text(encoding="utf-8")
    )
    assert stored[0]["status"] == "pending"


def test_cli_handshakes_approve_signs_with_the_operator_key(
    tmp_path: Path, operator_signer, monkeypatch, capsys
) -> None:
    from ract import cli
    from ract.handshake_registry import HandshakeRegistry

    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: x\n", encoding="utf-8")
    registry = HandshakeRegistry(tmp_path)
    registry.add("m1", "deploy", "ok")
    monkeypatch.setattr(
        "ract.policy.operator_key.read_passphrase",
        lambda prompt="", **_k: "throwaway passphrase for a test",
    )
    from ract.policy.unlock import SESSION_WINDOW

    SESSION_WINDOW.lock()
    code = cli.main(["handshakes", "approve", "m1", "--json", "--config", str(config)])
    assert code == 0
    out = capsys.readouterr().out
    try:
        data = json.loads(out)
    except json.JSONDecodeError as exc:
        # The next CI failure must show the pollutant, not just the position.
        pytest.fail(f"--json stdout was polluted: {out[:300]!r} ({exc})")
    assert data["status"] == "approved"
    assert registry.approval_state(registry.current("m1")) == "signed"
    assert registry.is_approved("m1")


# RACT 0.1.2 - Trust and tooling
