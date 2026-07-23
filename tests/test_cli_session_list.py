# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract session list CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_session_list_shows_saved_sessions(tmp_path):
    store = tmp_path / "sessions"
    store.mkdir()
    (store / "session-abc.json").write_text(
        json.dumps({"intent": "test"}), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "session",
            "list",
            "--store",
            str(store),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "session-abc" in result.stdout


def test_cli_session_list_empty_store(tmp_path):
    store = tmp_path / "sessions"
    store.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "session",
            "list",
            "--store",
            str(store),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "No sessions found" in result.stdout


# RACT 0.1.1 - Trust and tooling
