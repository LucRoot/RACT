"""Tests for the ract consolidate scan --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


_CODE_A = """\
def helper(value):
    return value * 2


def main():
    return helper(5)
"""

_CODE_B = """\
def helper(value):
    return value * 2


def main():
    return helper(7)
"""

_CODE_DIFFERENT = """\
class RocketLauncher:
    def launch(self):
        return "liftoff"
"""


def _run_consolidate_json(project_dir):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "consolidate",
            "scan",
            "--json",
            "--project-dir",
            str(project_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_consolidate_json_finds_duplicates(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "module_a.py").write_text(_CODE_A, encoding="utf-8")
    (src / "module_b.py").write_text(_CODE_B, encoding="utf-8")

    result = _run_consolidate_json(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert "summary" in data
    assert data["summary"]["proposals"] > 0
    assert len(data["issues"]) > 0
    assert len(data["files"]) >= 2


def test_cli_consolidate_json_empty_when_no_duplicates(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "module_a.py").write_text(_CODE_A, encoding="utf-8")
    (src / "module_c.py").write_text(_CODE_DIFFERENT, encoding="utf-8")

    result = _run_consolidate_json(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, dict)
    assert data["summary"]["proposals"] == 0
    assert data["issues"] == []
