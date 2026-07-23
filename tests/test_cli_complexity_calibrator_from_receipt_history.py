__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import json
import subprocess
import sys
from pathlib import Path


def test_complexity_calibrator_from_receipt_history(tmp_path):
    receipts_dir = tmp_path / "receipts"
    receipts_dir.mkdir()
    for i, score in enumerate([0.2, 0.5, 0.8], start=1):
        receipt = receipts_dir / f"run_{i}.json"
        receipt.write_text(
            json.dumps(
                {
                    "run_id": f"task_{i}",
                    "complexity_score": score,
                    "cost": score * 0.01,
                    "tokens": int(score * 1000),
                    "latency_ms": int(score * 500),
                    "tier": "low" if score < 0.4 else "medium" if score < 0.7 else "high",
                }
            ),
            encoding="utf-8",
        )
    cmd = [
        sys.executable,
        "-m",
        "rootact.cli",
        "calibrate",
        "--receipts-dir",
        str(receipts_dir),
    ]
    result = subprocess.run(
        cmd,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "Recommended tier thresholds" in result.stdout
    assert "low:" in result.stdout
    assert "medium:" in result.stdout
    assert "high:" in result.stdout
