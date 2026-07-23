from __future__ import annotations


"""Default cost-per-1k-token index for RACT provider presets.

These are rough market list prices (USD) as of the 0.1.2 release.  They let
``cost_tracker`` produce a sensible spend estimate even when a provider does
not return an explicit ``cost`` field.

Values are stored per 1k tokens so they are easy to compare with published
pricing pages.  ``estimate_cost`` converts to per-token internally.
"""

from typing import Any, Dict


COST_INDEX: Dict[str, Dict[str, Any]] = {
    "local": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "self-hosted; electricity/hardware not priced",
    },
    "openai": {
        "input_per_1k": 0.15,
        "output_per_1k": 0.60,
        "currency": "USD",
        "note": "gpt-4o-mini list pricing",
    },
    "anthropic": {
        "input_per_1k": 3.0,
        "output_per_1k": 15.0,
        "currency": "USD",
        "note": "claude-3-5-sonnet list pricing",
    },
    "zai": {
        "input_per_1k": 0.5,
        "output_per_1k": 1.0,
        "currency": "USD",
        "note": "representative low-cost frontier proxy",
    },
    "moonshot": {
        "input_per_1k": 0.5,
        "output_per_1k": 1.0,
        "currency": "USD",
        "note": "representative low-cost frontier proxy",
    },
    "openrouter": {
        "input_per_1k": 0.5,
        "output_per_1k": 1.0,
        "currency": "USD",
        "note": "varies by model; representative mid-market average",
    },
    # Common local/self-managed names that may appear in receipts.
    "qwen": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "local inference",
    },
    "bonsai": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "local inference",
    },
    "lfm": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "local inference",
    },
    "smollm3": {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "local inference",
    },
}


def get_cost_index(provider: str) -> Dict[str, Any]:
    """Return the cost index entry for ``provider`` (case-insensitive).

    Falls back to a zero-cost ``unknown`` entry when the provider is not
    catalogued, so callers never crash on an unseen provider name.
    """
    key = provider.lower()
    if key in COST_INDEX:
        return COST_INDEX[key]
    # Try a few common aliases.
    aliases = {
        "openai-compatible": "openrouter",
        "frontier": "anthropic",
        "claude": "anthropic",
        "gpt": "openai",
    }
    if key in aliases:
        return COST_INDEX[aliases[key]]
    return {
        "input_per_1k": 0.0,
        "output_per_1k": 0.0,
        "currency": "USD",
        "note": "unknown provider; no cost estimate available",
    }


def estimate_cost(
    provider: str,
    tokens: float | None = None,
    input_tokens: float = 0.0,
    output_tokens: float = 0.0,
) -> float:
    """Estimate spend in USD for a provider and token counts.

    If ``tokens`` is supplied and input/output breakdowns are not, the spend
    is approximated using the input price for the whole count.  This matches
    the common receipt shape where only ``total_tokens`` is recorded.
    """
    index = get_cost_index(provider)
    in_rate = float(index.get("input_per_1k", 0.0)) / 1000.0
    out_rate = float(index.get("output_per_1k", 0.0)) / 1000.0

    if input_tokens or output_tokens:
        return round(input_tokens * in_rate + output_tokens * out_rate, 8)

    total = float(tokens or 0.0)
    # When only a total is available, use the average of input and output
    # rates as a blended estimate. Providers with zero rates (local/unknown)
    # produce a zero-cost estimate.
    blended_rate = (in_rate + out_rate) / 2.0
    return round(total * blended_rate, 8)
