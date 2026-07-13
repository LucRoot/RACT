__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()
from rootact.ai_sbom import build_ai_manifest
import json

def test_ai_manifest_schema():
    receipts = [
        {
            "file": "example.py",
            "model_provider": "openai",
            "timestamp": "2026-07-12T12:00:00Z",
            "quality_score": 0.95,
            "receipt_hash": "abc123"
        },
        {
            "file": "another.py",
            "model_provider": "ollama",
            "timestamp": "2026-07-12T12:01:00Z",
            "quality_score": 0.89,
            "receipt_hash": "def456"
        }
    ]
    manifest = build_ai_manifest(receipts, "my-project")
    assert isinstance(manifest, dict)
    assert "metadata" in manifest
    assert "components" in manifest
    assert len(manifest["components"]) == len(receipts)
    for component in manifest["components"]:
        assert "file" in component
        assert "model_provider" in component
        assert "timestamp" in component
        assert "quality_score" in component
        assert "receipt_hash" in component
