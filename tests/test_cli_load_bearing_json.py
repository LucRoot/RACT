# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract load-bearing list --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def _run(args, project_dir):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "load-bearing",
            "list",
            *args,
            "--config",
            str(project_dir / "rootact.yaml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_load_bearing_json_finds_annotation(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "core.py").write_text(
        "# load-bearing: legacy billing parser\ndef parse_billing():\n    pass\n",
        encoding="utf-8",
    )

    result = _run(["--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["file"] == "src/core.py"
    assert "billing" in data[0]["reason"]


def test_cli_load_bearing_json_empty_when_clean(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir()
    (src / "clean.py").write_text("def helper():\n    pass\n", encoding="utf-8")

    result = _run(["--json"], tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == []
