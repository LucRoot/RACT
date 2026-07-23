"""Tests for the ract diff apply --json CLI output."""

from __future__ import annotations


import json
import subprocess
import sys


def test_cli_diff_apply_json_reports_applied(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    target = tmp_path / "src" / "foo.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line one\nline two\n", encoding="utf-8")
    patch = tmp_path / "change.diff"
    patch.write_text(
        "--- src/foo.txt\n+++ src/foo.txt\n@@ -1,2 +1,2 @@\n line one\n-line two\n+line two changed\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "diff",
            "apply",
            "--patch",
            str(patch),
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
    assert any(item["applied"] is True for item in data)


def test_cli_diff_apply_json_reports_failed(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    target = tmp_path / "src" / "foo.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line one\nline two\n", encoding="utf-8")
    patch = tmp_path / "broken.diff"
    patch.write_text(
        "--- src/foo.txt\n+++ src/foo.txt\n@@ -1,2 +1,2 @@\n line one\n-bogus\n+changed\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "diff",
            "apply",
            "--patch",
            str(patch),
            "--json",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert any(item["applied"] is False for item in data)


# RACT 0.1.2 - Trust and tooling
