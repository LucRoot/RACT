# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the ract plan diff CLI verb."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cli_plan_diff_reports_added_and_removed_steps(tmp_path):
    plan_a = tmp_path / "plan_a.json"
    plan_a.write_text(
        json.dumps(
            {
                "assumption": "test",
                "confidence": 0.9,
                "steps": [
                    {
                        "action": "edit",
                        "provider_hint": "local",
                        "expected_artifact": "old.py",
                    },
                    {
                        "action": "edit",
                        "provider_hint": "local",
                        "expected_artifact": "keep.py",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    plan_b = tmp_path / "plan_b.json"
    plan_b.write_text(
        json.dumps(
            {
                "assumption": "test",
                "confidence": 0.9,
                "steps": [
                    {
                        "action": "edit",
                        "provider_hint": "local",
                        "expected_artifact": "keep.py",
                    },
                    {
                        "action": "edit",
                        "provider_hint": "local",
                        "expected_artifact": "new.py",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "plan",
            "diff",
            str(plan_a),
            str(plan_b),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    added = [step.get("expected_artifact") for step in data["added_steps"]]
    removed = [step.get("expected_artifact") for step in data["removed_steps"]]
    assert "new.py" in added
    assert "old.py" in removed


# RACT 0.1.1 - Trust and tooling
