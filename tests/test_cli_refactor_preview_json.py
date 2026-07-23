# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract refactor --dry-run --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_refactor_preview_json_outputs_edits(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "module.py"
    src.write_text("def old_func():\n    return 1\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "refactor",
            "--old",
            "old_func",
            "--new",
            "new_func",
            "--dry-run",
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(edit.get("new_text") == "new_func" for edit in data)
    assert all("path" in edit for edit in data)


# RACT 0.1.2 - Trust and tooling
