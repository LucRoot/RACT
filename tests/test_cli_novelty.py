# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the RACT novelty CLI command."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import json

from rootact.cli import main


def _seed_project(project_dir):
    """Create a small codebase with enough chunks to train a dictionary."""
    (project_dir / "familiar.py").write_text(
        "def helper_function(x):\n    return x * 2\n\n" * 80,
        encoding="utf-8",
    )
    (project_dir / "familiar_two.py").write_text(
        "class DataStore:\n    def __init__(self):\n        self.items = []\n\n" * 40,
        encoding="utf-8",
    )
    (project_dir / "outlier.py").write_text(
        "class QuantumFluxCapacitor:\n    def engage(self):\n        return 1.21\n",
        encoding="utf-8",
    )


def test_cli_novelty_scan_text_output(capsys, tmp_path):
    _seed_project(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project: test\n", encoding="utf-8")

    code = main(["novelty", "scan", "--config", str(config)])
    out = capsys.readouterr().out

    assert code == 0
    assert "novelty scan" in out
    assert "familiar.py" in out
    assert "outlier.py" in out


def test_cli_novelty_scan_json_output(capsys, tmp_path):
    _seed_project(tmp_path)
    config = tmp_path / "rootact.yaml"
    config.write_text("project: test\n", encoding="utf-8")

    code = main(["novelty", "scan", "--json", "--config", str(config)])
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["has_dictionary"] is True
    assert "familiar.py" in payload["scores"]
    assert "outlier.py" in payload["scores"]


# RACT 0.1.1 - Trust and Tooling
