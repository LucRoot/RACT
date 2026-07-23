"""Tests for the ract skills list --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys
from pathlib import Path


def test_cli_skills_list_json_outputs_skills():
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "skills", "list", "--json"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_root),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert data
    assert all("name" in item and "description" in item for item in data)


# RACT 0.1.2 - Trust and tooling
