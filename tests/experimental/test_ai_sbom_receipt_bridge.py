"""Regression: ai_sbom accepts current-shape ``Receipt`` records.

This test locks the v0.1 to current bridge that module_03 lands. The
manifest reader must accept both shapes without raising ``KeyError``;
current-shape records are projected into the v0.1 SBOM record shape.

module_02 flagged the underlying drift (``ract ai-sbom`` failing with
``KeyError: 'file'`` on current ``Receipt`` records). module_03 owns the
fix as the natural v0.1 to current adapter home.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from ract.experimental.ai_sbom import build_ai_manifest
from ract.receipt import Receipt


def _current_receipt_dict(**overrides: str) -> dict[str, str]:
    base = {
        "run_id": "run-2026-08-17",
        "plan_hash": "deadbeef" * 8,
        "diff_hash": "cafef00d" * 8,
        "test_results": "passed",
        "signer_id": "session-abc",
        "signature": "sig-base64==",
    }
    base.update(overrides)
    return base


def test_current_receipt_dict_does_not_raise_keyerror() -> None:
    """The pre-fix behavior was a bare KeyError('file')."""
    manifest = build_ai_manifest([_current_receipt_dict()], "demo")
    assert len(manifest["components"]) == 1


def test_current_receipt_projects_plan_hash_into_file() -> None:
    manifest = build_ai_manifest([_current_receipt_dict()], "demo")
    component = manifest["components"][0]
    assert component["file"].startswith("plan:"), component["file"]
    # 12 chars of the plan_hash prefix.
    assert component["file"] == "plan:deadbeefdead"


def test_current_receipt_projects_signer_id_into_model_provider() -> None:
    manifest = build_ai_manifest([_current_receipt_dict()], "demo")
    assert manifest["components"][0]["model_provider"] == "session-abc"


def test_current_receipt_projects_signature_into_receipt_hash() -> None:
    manifest = build_ai_manifest([_current_receipt_dict()], "demo")
    assert manifest["components"][0]["receipt_hash"] == "sig-base64=="


@pytest.mark.parametrize(
    "test_results,expected",
    [
        ("passed", 1.0),
        ("pass", 1.0),
        ("failed", 0.0),
        ("fail", 0.0),
        ("skipped", None),
        ("", None),
    ],
)
def test_test_results_project_to_quality_score(
    test_results: str, expected: float | None
) -> None:
    receipt = _current_receipt_dict(test_results=test_results)
    manifest = build_ai_manifest([receipt], "demo")
    assert manifest["components"][0]["quality_score"] == expected


def test_dataclass_receipt_via_asdict_accepted() -> None:
    """The bridge accepts a real ``Receipt`` dataclass serialized via ``asdict``."""
    receipt = Receipt(
        run_id="r1",
        plan_hash="p" * 64,
        diff_hash="d" * 64,
        test_results="passed",
        signer_id="s1",
        signature="sig",
    )
    manifest = build_ai_manifest([asdict(receipt)], "demo")
    component = manifest["components"][0]
    assert component["model_provider"] == "s1"
    assert component["quality_score"] == 1.0


def test_v01_shape_still_works() -> None:
    """The v0.1 shape must remain a pass-through (no regression)."""
    v01 = {
        "file": "src/main.py",
        "model_provider": "qwen",
        "timestamp": "2026-07-18T00:00:00Z",
        "quality_score": 0.95,
        "receipt_hash": "abc123",
    }
    manifest = build_ai_manifest([v01], "demo")
    component = manifest["components"][0]
    assert component == v01


def test_mixed_batch_accepts_both_shapes() -> None:
    """A single call may mix v0.1 and current records."""
    manifest = build_ai_manifest(
        [
            {
                "file": "a.py",
                "model_provider": "qwen",
                "timestamp": "t1",
                "quality_score": 0.9,
                "receipt_hash": "h1",
            },
            _current_receipt_dict(),
        ],
        "demo",
    )
    assert len(manifest["components"]) == 2
    assert manifest["components"][0]["file"] == "a.py"
    assert manifest["components"][1]["file"].startswith("plan:")


def test_unknown_shape_raises_value_error_not_key_error() -> None:
    """An unrecognized shape must fail with a specific ValueError."""
    with pytest.raises(ValueError, match="Unrecognized receipt shape"):
        build_ai_manifest([{"unrelated": "field"}], "demo")


def test_cli_ai_sbom_reads_current_receipts(tmp_path: Path) -> None:
    """End-to-end: ``ract ai-sbom`` reads a JSON file of current receipts."""
    receipts_path = tmp_path / "receipts.json"
    receipts_path.write_text(json.dumps([_current_receipt_dict()]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "ract.cli", "ai-sbom", str(receipts_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["tool"] == "RACT"
    assert len(manifest["components"]) == 1
    assert manifest["components"][0]["file"].startswith("plan:")


# RACT 0.3.0
