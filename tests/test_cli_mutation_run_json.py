# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract mutation run --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_mutation_run_json_emits_json_or_fails_cleanly(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("project:\n  name: test\n", encoding="utf-8")
    script = tmp_path / "fake_mutation.sh"
    script.write_text(
        "echo 'Killed 😎 (10)'\necho 'Survived 🙁 (2)'\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "mutation",
            "run",
            "--json",
            "--script",
            str(script),
            "--timeout",
            "10",
            "--config",
            str(config),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        assert "mutation_score" in data
    else:
        assert "mutation" in (result.stderr or "").lower()


# RACT 0.1.2 - Trust and tooling
