# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for `ract rot baseline --plot`."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_rot_baseline_plot_missing_history(tmp_path):
    missing_history = tmp_path / "missing.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "rot",
            "baseline",
            "--history",
            str(missing_history),
            "--plot",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "No rot history to plot" in result.stdout


def test_rot_baseline_plot_empty_history(tmp_path):
    history = tmp_path / "history.jsonl"
    history.write_text("", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "rot",
            "baseline",
            "--history",
            str(history),
            "--plot",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "No rot history to plot" in result.stdout


def test_rot_baseline_plot_renders_chart(tmp_path):
    history = tmp_path / "history.jsonl"
    entries = [
        {"date": "2026-07-14T00:00:00+00:00", "duplication_ratio": 0.1},
        {"date": "2026-07-15T00:00:00+00:00", "duplication_ratio": 0.3},
        {"date": "2026-07-16T00:00:00+00:00", "duplication_ratio": 0.2},
        {"date": "2026-07-17T00:00:00+00:00", "duplication_ratio": 0.5},
    ]
    history.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "rot",
            "baseline",
            "--history",
            str(history),
            "--plot",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "duplication_ratio" in result.stdout
    assert "*" in result.stdout


def test_rot_baseline_plot_output_file(tmp_path):
    history = tmp_path / "history.jsonl"
    entries = [
        {"date": "2026-07-14T00:00:00+00:00", "duplication_ratio": 0.1},
        {"date": "2026-07-15T00:00:00+00:00", "duplication_ratio": 0.3},
    ]
    history.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    output = tmp_path / "chart.txt"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "rot",
            "baseline",
            "--history",
            str(history),
            "--plot",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "duplication_ratio" in text
    assert "*" in text
