from __future__ import annotations


"""CLI command for the RACT complexity-router calibrator.

``ract calibrate --receipts-dir <dir>`` reads historical RACT receipts,
extracts complexity/cost/tokens/latency observations, and recommends
low / medium / high tier thresholds for ``ComplexityRouter``.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from ract.complexity_calibrator import ComplexityCalibrator


def _extract_records(receipts_dir: Path) -> List[Dict[str, Any]]:
    """Read *.json receipts and pull calibration fields.

    The CLI is tolerant of real-world receipt shapes:
      - ``complexity_score`` is used directly if present.
      - Otherwise ``quality`` (assumed 0-100) is normalised to 0-1.
      - ``cost`` is used directly.
      - ``tokens`` is used directly if present.
      - ``latency`` or ``latency_ms`` is mapped to ``latency_ms``.
    """
    records: List[Dict[str, Any]] = []
    if not receipts_dir.is_dir():
        return records
    for path in sorted(receipts_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue

        score: float | None = None
        if "complexity_score" in data:
            score = float(data["complexity_score"])
        elif "quality" in data:
            quality = float(data["quality"])
            score = quality / 100.0 if quality > 1.0 else quality

        cost = float(data.get("cost") or 0.0)
        tokens = float(data.get("tokens") or 0.0)
        latency = float(data.get("latency_ms") or data.get("latency") or 0.0)

        if score is None:
            continue

        records.append(
            {
                "complexity_score": score,
                "cost": cost,
                "tokens": tokens,
                "latency_ms": latency,
                "tier": str(data.get("tier", "")),
                "task_id": str(data.get("run_id", data.get("task_id", path.stem))),
            }
        )
    return records


def _calibrate_command(args: list[str]) -> int:
    """Handle ``ract calibrate --receipts-dir <dir> [--json]``.

    Reads historical receipts, fits ``ComplexityCalibrator``, and prints
    recommended tier thresholds plus a per-tier summary.
    """
    parser = argparse.ArgumentParser(prog="ract calibrate")
    parser.add_argument(
        "--receipts-dir",
        required=True,
        type=Path,
        help="Directory containing receipt JSON files.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON instead of human text.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the calibration result to this JSON file.",
    )
    parsed = parser.parse_args(args)

    records = _extract_records(parsed.receipts_dir)
    if len(records) < 3:
        print(
            f"[ract] need at least 3 receipts with complexity_score or quality; found {len(records)}",
            file=sys.stderr,
        )
        return 1

    calibrator = ComplexityCalibrator().fit(records)
    result = calibrator.fit_summary()

    if parsed.output:
        parsed.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    if parsed.json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    thresholds = result["thresholds"]
    print("Recommended tier thresholds")
    print(f"  low:     <= {thresholds['low']}")
    print(f"  medium:  <= {thresholds['medium']}")
    print(f"  high:    <= {thresholds['high']}")
    print("  frontier: > high")
    print()
    print("Per-tier summary")
    for tier, summary in result["per_tier_summary"].items():
        if summary["count"] == 0:
            print(f"  {tier}: (no records)")
            continue
        print(
            f"  {tier}: n={summary['count']} "
            f"score=[{summary['min_score']}, {summary['max_score']}] "
            f"mean_cost={summary['mean_cost']} "
            f"mean_tokens={summary['mean_tokens']} "
            f"mean_latency_ms={summary['mean_latency_ms']}"
        )

    if parsed.output:
        print(f"\nWrote calibration to {parsed.output}")
    return 0
