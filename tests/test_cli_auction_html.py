# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract auction html-report CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys


def test_cli_auction_html_report_writes_file(tmp_path):
    config = tmp_path / "ract.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    output = tmp_path / "dead.html"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "auction",
            "html-report",
            "--output",
            str(output),
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    html = output.read_text(encoding="utf-8")
    assert "Dead Code" in html


# RACT 0.1.1 - Trust and tooling
