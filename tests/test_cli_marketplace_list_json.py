# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract skills marketplace list --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_marketplace_list_json_reads_catalog(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "name": "demo-skill",
                        "description": "A demonstration skill.",
                        "author": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "skills",
            "marketplace",
            "list",
            "--json",
            "--catalog",
            str(catalog),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(item.get("name") == "demo-skill" for item in data)


# RACT 0.1.2 - Trust and tooling
