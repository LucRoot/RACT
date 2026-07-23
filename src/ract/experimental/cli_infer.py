# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""CLI command for the RACT 3-tier inference router.

``ract infer <task> --config ract.yaml`` scores the task, selects the
cheapest healthy endpoint tier, and prints the routing decision without
actually invoking the model (dry-run by default).  This makes the router
configuration inspectable and testable before live use.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from ract.inference_router import InferenceRouter


def _default_call_fn(endpoint: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Dry-run call that returns the selected endpoint metadata."""
    return {"dry_run": True, "endpoint": endpoint.get("name", "unknown")}


def _load_router_config(config_path: Path) -> Dict[str, Any]:
    """Load the ``inference_router`` section from a RACT config file."""
    import yaml

    if not config_path.is_file():
        raise FileNotFoundError(f"config not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    router_cfg = data.get("inference_router")
    if not isinstance(router_cfg, dict):
        raise ValueError("config is missing the 'inference_router' section")
    return router_cfg


def _infer_command(args: list[str]) -> int:
    """Handle ``ract infer <task> [--config ...] [--json|--markdown]``."""
    parser = argparse.ArgumentParser(prog="ract infer")
    parser.add_argument("task", help="Task description to route.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("ract.yaml"),
        help="Path to ract.yaml with an inference_router section.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output JSON.",
    )
    parser.add_argument(
        "--markdown",
        dest="markdown_output",
        action="store_true",
        help="Output Markdown.",
    )
    parser.add_argument(
        "--live",
        dest="live",
        action="store_true",
        help="Actually invoke the selected endpoint (not implemented; reserved).",
    )

    parsed = parser.parse_args(args)

    try:
        router_cfg = _load_router_config(parsed.config)
    except FileNotFoundError as exc:
        print(f"[ract] {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"[ract] {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"[ract] missing dependency: {exc}", file=sys.stderr)
        return 1

    if parsed.live:
        print("[ract] live inference is not yet supported via CLI", file=sys.stderr)
        return 2

    router = InferenceRouter.from_config(router_cfg, call_fn=_default_call_fn)
    result = router.route(parsed.task)

    if not result.success:
        print(f"[ract] routing failed: {result.error}", file=sys.stderr)
        return 1

    if parsed.json_output:
        payload = {
            "task": result.task,
            "selected_tier": result.selected_tier,
            "selected_endpoint": result.selected_endpoint,
            "cross_tier_fallback": result.cross_tier_fallback,
            "attempts": [
                {
                    "endpoint": a.get("endpoint"),
                    "success": a.get("success"),
                    "error": a.get("error"),
                }
                for a in result.attempts
            ],
        }
        print(json.dumps(payload, indent=2))
    elif parsed.markdown_output:
        lines = ["# RACT Inference Router Selection", ""]
        lines.append(f"- **Task:** {result.task}")
        lines.append(f"- **Selected tier:** {result.selected_tier}")
        lines.append(f"- **Selected endpoint:** {result.selected_endpoint}")
        lines.append(f"- **Cross-tier fallback used:** {result.cross_tier_fallback}")
        print("\n".join(lines))
    else:
        print(f"selected tier: {result.selected_tier}")
        print(f"selected endpoint: {result.selected_endpoint}")
        if result.cross_tier_fallback:
            print("(cross-tier fallback)")

    return 0
