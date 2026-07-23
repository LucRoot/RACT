# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract handshakes --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


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
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"] == "m1"
    assert data["status"] == "approved"


# RACT 0.1.2 - Trust and tooling
