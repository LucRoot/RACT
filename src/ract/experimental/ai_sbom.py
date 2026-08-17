"""AI Provenance Manifest builder.

Accepts receipts in either the v0.1-era per-artifact shape (``file`` /
``model_provider`` / ``timestamp`` / ``quality_score`` / ``receipt_hash``)
or the current per-run ``Receipt`` shape (``run_id`` / ``plan_hash`` /
``diff_hash`` / ``test_results`` / ``signer_id`` / ``signature``). This
adapter is the v0.1 to current bridge that module_02 flagged and module_03
lands.

The manifest schema is stable at the v0.1 shape; the current-shape adapter
projects a per-run Receipt into a synthetic per-artifact record so downstream
SBOM consumers do not need to learn two shapes. The projection is lossless
where the current Receipt has a field, and explicit where it does not:

- ``file`` maps to ``plan:<plan_hash[:12]>`` (a run identifies a plan, not a
  single file, so the projected id names the plan that produced the artifact
  set),
- ``model_provider`` maps to ``signer_id`` (closest concept: the entity that
  authored/signed the receipt),
- ``timestamp`` is empty (current Receipt has no timestamp field; the loss
  is documented rather than fabricated),
- ``quality_score`` derives from ``test_results`` ("pass"/"passed" -> 1.0,
  "fail"/"failed" -> 0.0, otherwise None),
- ``receipt_hash`` maps to ``signature`` (the receipt's own audit anchor).
"""

from __future__ import annotations

from typing import Any


# Field sets that identify each receipt shape. Presence of ALL v0.1 keys ->
# v0.1 shape; presence of the current Receipt's identifying triple ->
# current shape. Mixed shapes are refused with a clear error.
_V01_FIELDS = {"file", "model_provider", "timestamp", "quality_score", "receipt_hash"}
_CURRENT_FIELDS = {"run_id", "plan_hash", "diff_hash", "test_results", "signer_id"}


def _quality_from_test_results(test_results: Any) -> float | None:
    """Project the current Receipt's free-form ``test_results`` string to a score.

    ``pass``/``passed`` -> 1.0, ``fail``/``failed`` -> 0.0, otherwise None.
    Non-string inputs return None. The projection is intentionally narrow so
    that only clearly-successful or clearly-failed runs claim a score.
    """
    if not isinstance(test_results, str):
        return None
    normalized = test_results.strip().lower()
    if normalized in {"pass", "passed"}:
        return 1.0
    if normalized in {"fail", "failed"}:
        return 0.0
    return None


def _project_current_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Project a current-shape ``Receipt`` dict into the v0.1 SBOM record shape."""
    plan_hash = str(receipt.get("plan_hash", ""))
    file_id = (
        f"plan:{plan_hash[:12]}" if plan_hash else f"run:{receipt.get('run_id', '')}"
    )
    return {
        "file": file_id,
        "model_provider": receipt.get("signer_id", ""),
        "timestamp": "",
        "quality_score": _quality_from_test_results(receipt.get("test_results")),
        "receipt_hash": receipt.get("signature", ""),
    }


def _normalize_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return a v0.1-shape record for either a v0.1 or current-shape receipt.

    Raises ``ValueError`` with a specific message if the shape is
    unrecognized, so operators see the mismatch rather than a bare KeyError.
    """
    keys = set(receipt.keys())
    if _V01_FIELDS.issubset(keys):
        # v0.1 pass-through (extra keys are ignored so callers can attach
        # side-band metadata without breaking the manifest projection).
        return {k: receipt[k] for k in _V01_FIELDS}
    if _CURRENT_FIELDS.issubset(keys):
        return _project_current_receipt(receipt)
    missing_v01 = _V01_FIELDS - keys
    missing_current = _CURRENT_FIELDS - keys
    raise ValueError(
        "Unrecognized receipt shape. Expected either the v0.1 shape "
        f"(missing: {sorted(missing_v01)}) or the current Receipt shape "
        f"(missing: {sorted(missing_current)})."
    )


def build_ai_manifest(receipts: list[dict[str, Any]], project: str) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "tool": "RACT",
        "version": "0.1.1",
        "metadata": {"component": "AI Provenance Manifest", "project": project},
        "components": [],
    }
    for receipt in receipts:
        manifest["components"].append(_normalize_receipt(receipt))
    return manifest
