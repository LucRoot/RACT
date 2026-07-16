# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the AI Provenance Manifest builder."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.ai_sbom import build_ai_manifest


def _receipt() -> dict:
    return {
        "file": "src/example.py",
        "model_provider": "openai/gpt-4o",
        "timestamp": "2026-07-16T00:00:00",
        "quality_score": 0.95,
        "receipt_hash": "abc123",
    }


def test_build_manifest_returns_expected_shape():
    manifest = build_ai_manifest([_receipt()], "ract")
    assert isinstance(manifest, dict)
    assert manifest.get("tool") == "RACT"
    assert "components" in manifest
    assert len(manifest["components"]) == 1
    component = manifest["components"][0]
    assert component["file"] == "src/example.py"
    assert component["model_provider"] == "openai/gpt-4o"


def test_empty_receipts_returns_empty_components():
    manifest = build_ai_manifest([], "ract")
    assert manifest["components"] == []


def test_manifest_includes_project_name():
    manifest = build_ai_manifest([_receipt()], "ract")
    assert manifest["metadata"]["project"] == "ract"


def test_manifest_version_and_component_label():
    manifest = build_ai_manifest([_receipt()], "ract")
    assert manifest["version"] == "0.1.1"
    assert manifest["metadata"]["component"] == "AI Provenance Manifest"


def test_multiple_receipts_are_appended():
    receipts = [_receipt(), _receipt()]
    receipts[1]["file"] = "src/other.py"
    manifest = build_ai_manifest(receipts, "ract")
    assert len(manifest["components"]) == 2
    assert manifest["components"][1]["file"] == "src/other.py"


# RACT 0.1.1 - Trust and tooling
