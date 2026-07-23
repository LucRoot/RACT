"""Tests for the ract handshakes --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_handshakes_review_json_shows_pending_items(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n")
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
            "review",
            "--json_review",
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


def test_cli_handshakes_review_json_shows_no_pending_items(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("provider: local\n")
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
                    "status": "approved",
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
            "review",
            "--json_review",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    items = json.loads(result.stdout)
    assert items == []
