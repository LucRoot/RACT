# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Compute a baseline rot-trend snapshot from project anti-rot metrics."""

from pathlib import Path
from typing import Any

from ract.compression_novelty_detector import CompressionNoveltyDetector
from ract.consolidate import ConsolidationScanner
from ract.dead_code_auction import DeadCodeAuction
from ract.experimental.rot_trend import TrendReport, record_snapshot
from ract.signature_guardian import SignatureGuardian


def compute_rot_trend_baseline(
    project_dir: Path | str,
    history_path: Path | str,
) -> TrendReport:
    """Record a rot-trend baseline for *project_dir* at *history_path*."""
    project_dir = Path(project_dir)

    consolidation = ConsolidationScanner(project_dir).scan()
    candidates = consolidation.metrics.get("candidates", 1) or 1
    duplication_ratio = len(consolidation.proposals) / candidates

    detector = CompressionNoveltyDetector(project_dir)
    fast_scan = detector.scan_project_fast()
    ratios: list[float] = []
    for entry in fast_scan.get("scores", {}).values():
        if isinstance(entry, dict):
            ratio = entry.get("ratio")
            if isinstance(ratio, (int, float)):
                ratios.append(float(ratio))
    novelty_score = sum(ratios) / len(ratios) if ratios else 0.0

    dead_code_count = len(DeadCodeAuction(project_dir).scan())
    missing_knot_count = len(SignatureGuardian(project_dir).scan())

    metrics: dict[str, Any] = {
        "duplication_ratio": round(duplication_ratio, 6),
        "novelty_score": round(novelty_score, 6),
        "dead_code_count": dead_code_count,
        "missing_knot_count": missing_knot_count,
    }
    return record_snapshot(metrics, Path(history_path))
