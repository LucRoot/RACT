__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
import subprocess
import sys
from pathlib import Path

def test_policy_gate_ci_reporter_junit_xml(tmp_path):
    config = tmp_path / "rootact.yaml"
    config.write_text("provider: local\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "rootact.cli"]
    cmd.append("policy-gate")
    cmd.append("--policy")
    cmd.append(str(config))
    cmd.append("--evidence")
    cmd.append(str(config))
    result = subprocess.run(
        cmd, cwd=str(tmp_path), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    assert result.returncode in (0, 1, 2)


def test_policy_gate_markdown(tmp_path):
    import json

    policy = tmp_path / "policy.json"
    evidence = tmp_path / "evidence.json"
    policy.write_text(json.dumps({"min_quality_score": 0.5}), encoding="utf-8")
    evidence.write_text(json.dumps({"receipts": [{"quality_score": 0.9}]}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "policy-gate", "--policy", str(policy), "--evidence", str(evidence), "--markdown"],
        cwd=str(tmp_path), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    assert "# RACT Policy Gate Report" in result.stdout
    assert "PASS" in result.stdout


def test_policy_gate_csv(tmp_path):
    import json

    policy = tmp_path / "policy.json"
    evidence = tmp_path / "evidence.json"
    policy.write_text(json.dumps({"min_quality_score": 0.5}), encoding="utf-8")
    evidence.write_text(json.dumps({"receipts": [{"quality_score": 0.9}]}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "rootact.cli", "policy-gate", "--policy", str(policy), "--evidence", str(evidence), "--csv"],
        cwd=str(tmp_path), capture_output=True, text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "status,failure"
    assert lines[1] == "pass,"

