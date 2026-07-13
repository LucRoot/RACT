from typing import List, Dict
import json

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

def build_ai_manifest(receipts: List[Dict], project: str) -> Dict:
    manifest = {"metadata": {"component": "AI Provenance Manifest"}}
    manifest["components"] = []
    for receipt in receipts:
        file_name = receipt["file"]
        model_provider = receipt["model_provider"]
        timestamp = receipt["timestamp"]
        quality_score = receipt["quality_score"]
        receipt_hash = receipt["receipt_hash"]
        manifest["components"].append({
            "file": file_name,
            "model_provider": model_provider,
            "timestamp": timestamp,
            "quality_score": quality_score,
            "receipt_hash": receipt_hash
        })
    return manifest
