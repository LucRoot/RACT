# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import subprocess
import sys

import pytest

_VERBS = [
    (["--help"], 0),
    (["plan", "--help"], 0),
    (["run", "--help"], 0),
    (["skills", "list"], 0),
    (["skills", "marketplace", "list"], 0),
    (["marketplace", "list"], 0),
    (["consolidate", "--help"], 0),
    (["release", "--help"], 0),
    (["fence", "--help"], 0),
    (["doctor", "--help"], 0),
    (["reflect", "--help"], 0),
    (["repair", "--help"], 0),
    (["audit", "--help"], 0),
    (["init", "--help"], 0),
]


@pytest.mark.parametrize("args, expected", _VERBS)
def test_verb_smoke(args: list[str], expected: int) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == expected, result.stderr
    assert "Traceback" not in result.stderr
    assert "unrecognized arguments" not in result.stderr
