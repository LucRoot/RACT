# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Longitudinal rot trend report for RACT.

Appends dated anti-rot snapshots to a JSONL history and computes deltas,
direction, and a simple rolling slope so teams can see whether the codebase
is healing or decaying across agent runs.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


METRIC_KEYS = [
    "duplication_ratio",
    "novelty_score",
    "dead_code_count",
    "missing_knot_count",
]


@dataclass
class TrendReport:
    snapshot: dict
    previous: Optional[dict]
    deltas: Optional[dict]
    direction: str
    slope: Optional[dict]


def _direction_for(metric: str, delta: float) -> int:
    """Return +1 if a positive delta is good, -1 if negative is good, 0 if neutral."""
    if metric == "novelty_score":
        return 1
    return -1


def _compute_direction(deltas: dict) -> str:
    """Return 'improving', 'worsening', or 'stable' based on delta signs."""
    improving = []
    worsening = []
    for key, value in deltas.items():
        if value is None:
            continue
        sign = _direction_for(key, value)
        if sign == 0:
            continue
        if value * sign > 0:
            improving.append(key)
        elif value * sign < 0:
            worsening.append(key)
    if improving and not worsening:
        return "improving"
    if worsening and not improving:
        return "worsening"
    return "stable"


def _compute_slope(history: list[dict], window: int) -> Optional[dict]:
    """Return average delta per metric over the last window snapshots."""
    if len(history) < 2:
        return None
    recent = history[-window:]
    if len(recent) < 2:
        return None
    slope: dict[str, Optional[float]] = {}
    for key in METRIC_KEYS:
        values: list[Optional[float]] = [snap.get(key) for snap in recent]
        numeric_values = [v for v in values if v is not None]
        if len(numeric_values) < 2:
            slope[key] = None
            continue
        slope[key] = (numeric_values[-1] - numeric_values[0]) / (
            len(numeric_values) - 1
        )
    return slope


def record_snapshot(
    metrics: dict[str, Any],
    history_path: Path,
    window: int = 3,
) -> TrendReport:
    """Append a snapshot and return a trend report."""
    history_path = Path(history_path)
    snapshot: dict[str, Any] = {"date": datetime.now(timezone.utc).isoformat()}
    for key in METRIC_KEYS:
        snapshot[key] = metrics.get(key)

    history: list[dict] = []
    if history_path.is_file():
        try:
            with history_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        history.append(json.loads(line))
        except (OSError, json.JSONDecodeError):
            history = []

    previous = history[-1] if history else None

    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot, separators=(",", ":")) + "\n")

    deltas: Optional[dict[str, Optional[float]]] = None
    if previous is not None:
        deltas = {}
        for key in METRIC_KEYS:
            prev: Any = previous.get(key)
            curr: Any = snapshot.get(key)
            if prev is None or curr is None:
                deltas[key] = None
            else:
                deltas[key] = float(curr) - float(prev)

    direction = _compute_direction(deltas) if deltas else "stable"
    slope = _compute_slope(history + [snapshot], window) if history else None

    # Simplify the returned snapshot to omit the internal date field for tests.
    report_snapshot: dict[str, Any] = {key: snapshot[key] for key in METRIC_KEYS}
    return TrendReport(
        snapshot=report_snapshot,
        previous=previous,
        deltas=deltas,
        direction=direction,
        slope=slope,
    )


# RACT 0.1.2 - Trust and tooling
