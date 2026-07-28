from __future__ import annotations


import json
import subprocess
import sys
from pathlib import Path


def test_repro_manifest_basic_json_output(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    plan_file.write_text(json.dumps({"steps": ["a", "b"]}), encoding="utf-8")
    config_file.write_text(json.dumps({"model": "qwen"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "repro-manifest",
            "--intent",
            "test intent",
            "--plan",
            str(plan_file),
            "--config",
            str(config_file),
            "--fingerprint",
            "fp-123",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["intent"] == "test intent"
    assert data["fingerprint"] == "fp-123"
    assert "plan_hash" in data
    assert "config_hash" in data
    assert "manifest_hash" in data
    assert "environment" in data


def test_repro_manifest_derives_fingerprint(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    plan_file.write_text(json.dumps({"steps": ["x"]}), encoding="utf-8")
    config_file.write_text(json.dumps({"temp": 0.7}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "repro-manifest",
            "--intent",
            "derive fingerprint",
            "--plan",
            str(plan_file),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["fingerprint"]
    assert isinstance(data["fingerprint"], str)


def test_repro_manifest_reads_fingerprint_from_receipt(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    receipt_file = tmp_path / "receipt.json"
    plan_file.write_text(json.dumps({"steps": ["y"]}), encoding="utf-8")
    config_file.write_text(json.dumps({"temp": 0.5}), encoding="utf-8")
    receipt_file.write_text(
        json.dumps({"run_id": "r1", "fingerprint": "fp-from-receipt"}),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "repro-manifest",
            "--intent",
            "from receipt",
            "--plan",
            str(plan_file),
            "--config",
            str(config_file),
            "--fingerprint-file",
            str(receipt_file),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["fingerprint"] == "fp-from-receipt"


def test_repro_manifest_writes_output_file(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    output_file = tmp_path / "manifest.json"
    plan_file.write_text(json.dumps({"steps": ["z"]}), encoding="utf-8")
    config_file.write_text(json.dumps({"model": "bonsai"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "repro-manifest",
            "--intent",
            "write output",
            "--plan",
            str(plan_file),
            "--config",
            str(config_file),
            "--fingerprint",
            "fp-out",
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
    assert data["fingerprint"] == "fp-out"


def test_repro_manifest_missing_plan_fails(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"model": "qwen"}), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ract.cli",
            "repro-manifest",
            "--intent",
            "missing plan",
            "--plan",
            str(tmp_path / "missing.json"),
            "--config",
            str(config_file),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "file not found" in result.stderr


def test_repro_manifest_manifest_hash_stable(tmp_path: Path) -> None:
    plan_file = tmp_path / "plan.json"
    config_file = tmp_path / "config.json"
    plan_file.write_text(json.dumps({"b": 2, "a": 1}), encoding="utf-8")
    config_file.write_text(json.dumps({"z": True, "y": False}), encoding="utf-8")

    def run() -> dict:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ract.cli",
                "repro-manifest",
                "--intent",
                "stable",
                "--plan",
                str(plan_file),
                "--config",
                str(config_file),
                "--fingerprint",
                "fp-stable",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    m1 = run()
    m2 = run()
    assert m1["manifest_hash"] == m2["manifest_hash"]
