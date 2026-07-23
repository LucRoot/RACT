from __future__ import annotations


import json
import subprocess
import sys
from pathlib import Path


def _receipt(
    score: float, cost: float, tokens: float = 0.0, latency: float = 0.0
) -> dict:
    return {
        "complexity_score": score,
        "cost": cost,
        "tokens": tokens,
        "latency_ms": latency,
        "run_id": f"run-{score}-{cost}",
    }


def test_calibrate_json_output(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    records = [
        _receipt(0.05, 1.0),
        _receipt(0.10, 2.0),
        _receipt(0.40, 10.0),
        _receipt(0.80, 50.0),
        _receipt(0.95, 200.0),
    ]
    for i, rec in enumerate(records):
        (receipts_dir / f"run_{i}.json").write_text(json.dumps(rec), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "calibrate",
            "--receipts-dir",
            str(receipts_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "thresholds" in data
    assert "per_tier_summary" in data
    thresholds = data["thresholds"]
    assert thresholds["low"] < thresholds["medium"] < thresholds["high"]


def test_calibrate_human_output(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    for i, rec in enumerate(
        [
            _receipt(0.05, 1.0),
            _receipt(0.50, 50.0),
            _receipt(0.90, 300.0),
        ]
    ):
        (receipts_dir / f"run_{i}.json").write_text(json.dumps(rec), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "calibrate",
            "--receipts-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "Recommended tier thresholds" in result.stdout
    assert "low:" in result.stdout


def test_calibrate_writes_output_file(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    output_file = tmp_path / "calibration.json"
    for i, rec in enumerate(
        [
            _receipt(0.05, 1.0),
            _receipt(0.50, 50.0),
            _receipt(0.90, 300.0),
        ]
    ):
        (receipts_dir / f"run_{i}.json").write_text(json.dumps(rec), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "calibrate",
            "--receipts-dir",
            str(receipts_dir),
            "--output",
            str(output_file),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert output_file.is_file()
    data = json.loads(output_file.read_text(encoding="utf-8"))
    assert "thresholds" in data


def test_calibrate_falls_back_to_quality(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    records = [
        {"quality": 10.0, "cost": 1.0, "latency": 100.0},
        {"quality": 50.0, "cost": 25.0, "latency": 500.0},
        {"quality": 90.0, "cost": 150.0, "latency": 2000.0},
    ]
    for i, rec in enumerate(records):
        (receipts_dir / f"run_{i}.json").write_text(json.dumps(rec), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "calibrate",
            "--receipts-dir",
            str(receipts_dir),
            "--json",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["thresholds"]["low"] < data["thresholds"]["medium"]


def test_calibrate_fails_with_too_few_receipts(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    (receipts_dir / "run_0.json").write_text(
        json.dumps({"complexity_score": 0.5, "cost": 1.0}), encoding="utf-8"
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "calibrate",
            "--receipts-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "need at least 3 receipts" in result.stderr
