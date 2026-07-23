# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract explain --json CLI output."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_explain_plan_json_outputs_fields(tmp_path):
    plan = {
        "assumption": "add greeting",
        "confidence": 0.9,
        "steps": [
            {
                "action": "create hello.py",
                "provider_hint": "local",
                "expected_artifact": "hello.py",
            }
        ],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "explain",
            "--plan",
            str(plan_path),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["assumption"] == "add greeting"
    assert data["confidence"] == 0.9
    assert any(step.get("expected_artifact") == "hello.py" for step in data["steps"])


# RACT 0.1.2 - Trust and tooling
