# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `ract rot baseline` CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rootact.cli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_rot_baseline_json_emits_report(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "module.py").write_text(
        "def helper(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    history = tmp_path / "rot_history.jsonl"

    result = _run(
        [
            "rot",
            "baseline",
            str(project_dir),
            "--history",
            str(history),
            "--json",
        ]
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["direction"] == "stable"
    assert payload["previous"] is None
    assert payload["deltas"] is None
    assert payload["slope"] is None
    assert "duplication_ratio" in payload["snapshot"]
    assert "novelty_score" in payload["snapshot"]
    assert "dead_code_count" in payload["snapshot"]
    assert "missing_knot_count" in payload["snapshot"]
    assert history.is_file()


def test_cli_rot_baseline_second_run_has_deltas(tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "module.py").write_text(
        "def helper(x):\n    return x * 2\n",
        encoding="utf-8",
    )
    history = tmp_path / "rot_history.jsonl"

    _run(
        [
            "rot",
            "baseline",
            str(project_dir),
            "--history",
            str(history),
            "--json",
        ]
    )
    result = _run(
        [
            "rot",
            "baseline",
            str(project_dir),
            "--history",
            str(history),
            "--json",
        ]
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["previous"] is not None
    assert payload["deltas"] is not None
    assert payload["slope"] is not None


# RACT 0.1.2 - Trust and tooling
