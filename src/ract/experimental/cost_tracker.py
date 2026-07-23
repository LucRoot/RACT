from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

"""Token-cost aggregation and budget status helpers."""

import json
from pathlib import Path
from typing import Any

from ract.experimental.provider_cost_index import estimate_cost


def aggregate_costs(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate token and estimated spend per provider and overall."""
    per_provider: dict[str, dict[str, float]] = {}
    total_tokens = 0.0
    total_cost = 0.0
    for receipt in receipts:
        provider = receipt.get("provider") or "unknown"
        tokens = float(
            receipt.get("tokens") or (receipt.get("usage") or {}).get("total_tokens", 0)
        )
        raw_cost = receipt.get("cost")
        if raw_cost is None or raw_cost == "":
            cost = estimate_cost(
                provider,
                tokens=tokens,
                input_tokens=float(receipt.get("input_tokens") or 0),
                output_tokens=float(receipt.get("output_tokens") or 0),
            )
        else:
            cost = float(raw_cost)
        entry = per_provider.setdefault(provider, {"tokens": 0.0, "cost": 0.0})
        entry["tokens"] += tokens
        entry["cost"] += cost
        total_tokens += tokens
        total_cost += cost
    return {
        "total": {"tokens": total_tokens, "cost": round(total_cost, 6)},
        "per_provider": per_provider,
    }


def budget_status(totals: dict[str, Any], budget: dict[str, Any]) -> dict[str, Any]:
    """Return a budget status summary.

    Accepts either a per-provider totals dict (as returned by aggregate_costs)
    or a simple total cost dict for quick checks.
    """
    if "cost" in totals:
        spent = float(totals["cost"])
    elif "total" in totals:
        spent = float(totals["total"].get("cost", 0.0))
    else:
        spent = sum(float(p.get("cost", 0.0)) for p in totals.values())

    budget_cost = float(budget.get("cost", 0.0))
    remaining = round(budget_cost - spent, 6)
    return {
        "spent": round(spent, 6),
        "remaining": remaining,
        "over_budget": remaining < 0,
    }


def load_receipts(path: Path) -> list[dict[str, Any]]:
    """Load newline-delimited JSON receipt records."""
    if not path.exists():
        return []
    receipts: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            receipts.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return receipts
