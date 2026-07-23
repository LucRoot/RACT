from __future__ import annotations


"""Canonical reproducibility manifest for RACT runs.

Builds a deterministic, JSON-serializable manifest that captures intent, plan,
configuration, environment markers, and a run fingerprint so two runs can be
proven equivalent.
"""

import hashlib
import json
import platform
import sys
from typing import Any, Dict


def _canonical_json(obj: Any) -> str:
    """Return a stable, sorted JSON representation for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _environment_markers() -> Dict[str, Any]:
    """Collect environment markers relevant to reproducibility."""
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }


def build_manifest(
    intent: str,
    plan: Dict[str, Any],
    config: Dict[str, Any],
    fingerprint: str,
) -> Dict[str, Any]:
    """Return a canonical reproducibility manifest.

    The manifest includes:
      - ``intent``: the original task intent.
      - ``plan_hash``: SHA-256 of the canonical JSON plan.
      - ``config_hash``: SHA-256 of the canonical JSON config.
      - ``environment``: host/environment markers.
      - ``fingerprint``: caller-supplied run fingerprint.
      - ``manifest_hash``: SHA-256 of the canonical manifest content
        (excluding this field).

    Args:
        intent: Task intent or description.
        plan: Planning data (dict, list, or other JSON-serializable structure).
        config: Configuration data.
        fingerprint: Run fingerprint (e.g., from RACT run fingerprint module).

    Returns:
        A deterministic dict describing the run.
    """
    plan_hash = _sha256_hex(_canonical_json(plan))
    config_hash = _sha256_hex(_canonical_json(config))
    environment = _environment_markers()

    body = {
        "intent": intent,
        "plan_hash": plan_hash,
        "config_hash": config_hash,
        "environment": environment,
        "fingerprint": fingerprint,
    }
    body["manifest_hash"] = _sha256_hex(_canonical_json(body))
    return body
