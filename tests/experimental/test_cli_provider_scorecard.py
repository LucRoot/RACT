__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys
from pathlib import Path


def test_provider_scorecard_json(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    for i in range(10):
        receipt = receipts_dir / f"run_{i}.json"
        receipt.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "success": 1 if i < 8 else 0,
                    "latency": 1.0 + i,
                    "quality": 50.0 + i,
                    "cost": 0.1 * i,
                }
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "provider",
            "scorecard",
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
    assert "local" in data
    assert data["local"]["success_rate"] == 0.8
    assert data["local"]["sample_count"] == 10


def test_provider_scorecard_human_output(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    for i in range(10):
        receipt = receipts_dir / f"run_{i}.json"
        receipt.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "success": 1,
                    "latency": 1.0,
                    "quality": 50.0,
                    "cost": 0.1,
                }
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "provider",
            "scorecard",
            "--receipts-dir",
            str(receipts_dir),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "local:" in result.stdout
    assert "success_rate" in result.stdout


def test_provider_scorecard_csv(tmp_path: Path) -> None:
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    for i in range(10):
        receipt = receipts_dir / f"run_{i}.json"
        receipt.write_text(
            json.dumps(
                {
                    "provider": "local",
                    "success": 1 if i < 8 else 0,
                    "latency": 1.0 + i,
                    "quality": 50.0 + i,
                    "cost": 0.1 * i,
                }
            ),
            encoding="utf-8",
        )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "rootact.cli",
            "provider",
            "scorecard",
            "--receipts-dir",
            str(receipts_dir),
            "--csv",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0].startswith("provider,")
    assert any(line.startswith("local,") for line in lines[1:])
