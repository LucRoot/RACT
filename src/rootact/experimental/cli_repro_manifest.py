# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""CLI command for the RACT reproducibility manifest.

``ract repro-manifest --intent <text> --plan <file> --config <file>`` builds a
canonical, deterministic manifest that can be used to prove two RACT runs were
equivalent.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from rootact.reproducibility_manifest import build_manifest


def _load_json_file(path: Path) -> Any:
    """Load a JSON file and return its parsed contents."""
    if not path.is_file():
        raise FileNotFoundError(f"file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_fingerprint(plan: dict, config: dict) -> str:
    """Derive a deterministic run fingerprint from plan + config.

    We build the fingerprint locally rather than calling ``fingerprint_run``,
    which expects a run receipt with ``plan_steps`` and ``artifact_hashes``.
    """
    canonical = json.dumps(
        {"plan": plan, "config": config},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _repro_manifest_command(args: list[str]) -> int:
    """Handle ``ract repro-manifest --intent ... --plan ... --config ...``.

    Builds a canonical reproducibility manifest from intent, plan, and config.
    A fingerprint can be supplied explicitly or derived from the plan/config.
    """
    parser = argparse.ArgumentParser(prog="ract repro-manifest")
    parser.add_argument(
        "--intent",
        required=True,
        help="Task intent or description.",
    )
    parser.add_argument(
        "--plan",
        required=True,
        type=Path,
        help="Path to a JSON file containing the plan data.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to a JSON file containing the config data.",
    )
    parser.add_argument(
        "--fingerprint",
        help="Run fingerprint string (optional; derived if omitted).",
    )
    parser.add_argument(
        "--fingerprint-file",
        type=Path,
        help="Path to a JSON receipt from which to extract the run fingerprint.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the manifest to this JSON file (still printed to stdout).",
    )
    parsed = parser.parse_args(args)

    try:
        plan = _load_json_file(parsed.plan)
        config = _load_json_file(parsed.config)
    except FileNotFoundError as exc:
        print(f"[rootact] {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[rootact] invalid JSON: {exc}", file=sys.stderr)
        return 1

    fingerprint: str | None = parsed.fingerprint
    if parsed.fingerprint_file:
        try:
            receipt = _load_json_file(parsed.fingerprint_file)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"[rootact] {exc}", file=sys.stderr)
            return 1
        fingerprint = receipt.get("fingerprint") or receipt.get("run_fingerprint")
    if not fingerprint:
        fingerprint = _derive_fingerprint(plan, config)

    manifest = build_manifest(
        intent=parsed.intent,
        plan=plan,
        config=config,
        fingerprint=fingerprint,
    )

    if parsed.output:
        parsed.output.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0
