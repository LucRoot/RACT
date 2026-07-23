# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the `ract novelty scan --timeout` guard."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json
import time
from pathlib import Path
from unittest.mock import patch

from ract.cli import main


def test_cli_novelty_scan_timeout_returns_partial_json(capsys, tmp_path: Path):
    """A deep scan that exceeds --timeout returns a JSON result with timeout_reached."""
    config = tmp_path / "ract.yaml"
    config.write_text("project: test\n", encoding="utf-8")

    def _slow_scan(_self):
        time.sleep(2.0)
        return {"has_dictionary": True, "sample_count": 1, "scores": {}}

    with patch(
        "ract.compression_novelty_detector.CompressionNoveltyDetector.scan_project",
        _slow_scan,
    ):
        code = main(
            [
                "novelty",
                "scan",
                "--deep",
                "--config",
                str(config),
                "--json",
                "--timeout",
                "0.1",
            ]
        )

    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(out)
    assert payload["timeout_reached"] is True
    assert payload["timeout_seconds"] == 0.1
    assert payload["scores"] == {}


def test_cli_novelty_scan_default_fast_finishes_before_timeout(capsys, tmp_path: Path):
    """The default scan uses fast mode and completes normally."""
    config = tmp_path / "ract.yaml"
    config.write_text("project: test\n", encoding="utf-8")
    (tmp_path / "familiar.py").write_text(
        "def helper(x):\n    return x * 2\n" * 20,
        encoding="utf-8",
    )

    code = main(
        [
            "novelty",
            "scan",
            "--config",
            str(config),
            "--json",
            "--timeout",
            "30",
        ]
    )

    out = capsys.readouterr().out
    assert code == 0, out
    payload = json.loads(out)
    assert "timeout_reached" not in payload
    assert "scores" in payload


# RACT 0.1.2 - Trust and tooling
