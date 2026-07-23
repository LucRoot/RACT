# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract coverage badge CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_coverage_badge_writes_shields_json(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    pkg = project / "ract"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "module.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    tests = project / "tests"
    tests.mkdir()
    (tests / "test_module.py").write_text(
        "from ract.module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    config = project / "ract.yaml"
    config.write_text(
        "project:\n  name: test\ncoverage_gate:\n  timeout: 60.0\n",
        encoding="utf-8",
    )
    badge = project / "badge.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "coverage",
            "badge",
            "--output",
            str(badge),
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert badge.is_file()
    data = json.loads(badge.read_text(encoding="utf-8"))
    assert data["label"] == "coverage"
    assert "%" in data["message"]


# RACT 0.1.2 - Trust and tooling
