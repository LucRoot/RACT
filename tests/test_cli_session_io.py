# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract session export/import CLI verbs."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_session_export_import_roundtrip(tmp_path):
    store = tmp_path / "sessions"
    store.mkdir()
    (store / "my-session.json").write_text(
        json.dumps(
            {
                "intent": "test intent",
                "plan": {"assumption": "test", "confidence": 0.9, "steps": []},
            }
        ),
        encoding="utf-8",
    )

    export_path = tmp_path / "exported.json"
    export_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "session",
            "export",
            "--session",
            "my-session",
            "--output",
            str(export_path),
            "--store",
            str(store),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert export_result.returncode == 0, export_result.stderr
    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["session_id"] == "my-session"
    assert exported["state"]["intent"] == "test intent"

    import_store = tmp_path / "imported_sessions"
    import_store.mkdir()
    import_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "session",
            "import",
            "--input",
            str(export_path),
            "--store",
            str(import_store),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert import_result.returncode == 0, import_result.stderr
    imported = json.loads(
        (import_store / "my-session.json").read_text(encoding="utf-8")
    )
    assert imported["intent"] == "test intent"


# RACT 0.1.2 - Trust and tooling
