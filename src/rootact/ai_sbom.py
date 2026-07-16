from __future__ import annotations

from typing import Any

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()


def build_ai_manifest(receipts: list[dict[str, Any]], project: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "tool": "RACT",
        "version": "0.1.1",
        "metadata": {"component": "AI Provenance Manifest", "project": project},
        "components": [],
    }
    for receipt in receipts:
        manifest["components"].append(
            {
                "file": receipt["file"],
                "model_provider": receipt["model_provider"],
                "timestamp": receipt["timestamp"],
                "quality_score": receipt["quality_score"],
                "receipt_hash": receipt["receipt_hash"],
            }
        )
    return manifest
