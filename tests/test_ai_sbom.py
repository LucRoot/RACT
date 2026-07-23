__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.ai_sbom import build_ai_manifest


def test_build_ai_manifest_with_empty_receipts():
    manifest = build_ai_manifest([], "demo")
    assert manifest["tool"] == "RACT"
    assert manifest["version"] == "0.1.1"
    assert manifest["metadata"] == {
        "component": "AI Provenance Manifest",
        "project": "demo",
    }
    assert manifest["components"] == []


def test_build_ai_manifest_maps_receipt_fields():
    receipts = [
        {
            "file": "src/main.py",
            "model_provider": "qwen",
            "timestamp": "2026-07-18T00:00:00Z",
            "quality_score": 0.95,
            "receipt_hash": "abc123",
        }
    ]
    manifest = build_ai_manifest(receipts, "demo")
    assert len(manifest["components"]) == 1
    component = manifest["components"][0]
    assert component["file"] == "src/main.py"
    assert component["model_provider"] == "qwen"
    assert component["timestamp"] == "2026-07-18T00:00:00Z"
    assert component["quality_score"] == 0.95
    assert component["receipt_hash"] == "abc123"


def test_build_ai_manifest_preserves_order_and_multiple_receipts():
    receipts = [
        {
            "file": "a.py",
            "model_provider": "qwen",
            "timestamp": "t1",
            "quality_score": 0.9,
            "receipt_hash": "h1",
        },
        {
            "file": "b.py",
            "model_provider": "bonsai",
            "timestamp": "t2",
            "quality_score": 0.8,
            "receipt_hash": "h2",
        },
    ]
    manifest = build_ai_manifest(receipts, "demo")
    assert [c["file"] for c in manifest["components"]] == ["a.py", "b.py"]
    assert manifest["components"][1]["model_provider"] == "bonsai"


# RACT 0.1.1 - Trust and Tooling
