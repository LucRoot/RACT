__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import json
import subprocess
import sys


def test_cost_summary_json(tmp_path):
    receipts = tmp_path / "receipts.json"
    receipts.write_text(
        json.dumps({"provider": "local", "usage": {"total_tokens": 1000}}) + "\n" +
        json.dumps({"provider": "openai", "usage": {"total_tokens": 500}}) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "cost", "summary", "--receipts", str(receipts), "--json"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert "aggregate" in data
    assert data["aggregate"]["total"]["cost"] > 0


def test_cost_summary_csv(tmp_path):
    receipts = tmp_path / "receipts.json"
    receipts.write_text(
        json.dumps({"provider": "local", "usage": {"total_tokens": 100}}) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "cost", "summary", "--receipts", str(receipts), "--csv"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "provider,tokens,cost" in result.stdout
    assert "total," in result.stdout
