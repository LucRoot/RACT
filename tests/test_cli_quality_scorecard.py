__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys
from pathlib import Path


def test_quality_scorecard_json(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "quality",
            "scorecard",
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["passed"] is True
    assert data["total"] == 100.0
    assert "signals" in data


def test_quality_scorecard_human_output(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "quality",
            "scorecard",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "passed:" in result.stdout
    assert "total:" in result.stdout
