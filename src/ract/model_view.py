"""Lines for ``/model``: one block per configured provider (B-058).

Pure text. The caller passes the config's provider block, the manager's
name and the names whose host only the repository chose. Nothing here reads
a key: the block shows the host, never the URL path or any key field.
"""

from __future__ import annotations

import textwrap
from typing import Any
from urllib.parse import urlsplit

from ract.session_events import safe_text

CAPABILITY_HINT = "not checked; run ract doctor --check-providers"
NAMED = "(named by this repository's ract.yaml)"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def price_text(slot: dict[str, Any]) -> str:
    """Price per million tokens, or 'price unknown' unless both costs are set."""
    cost_in = _number(slot.get("input_cost_per_1k"))
    cost_out = _number(slot.get("output_cost_per_1k"))
    if cost_in is None or cost_out is None:
        return "price unknown"
    return f"price {cost_in * 1000:.2f} in, {cost_out * 1000:.2f} out per 1M tokens"


def host_text(slot: dict[str, Any]) -> str:
    url = slot.get("url") or slot.get("base_url")
    if not isinstance(url, str) or not url:
        return "(no url)"
    return safe_text(urlsplit(url).netloc or "(no url)")


def model_blocks(
    providers: dict[str, Any],
    manager: str,
    named: set[str],
    width: int,
) -> list[str]:
    """Every output line, wrapped to *width* columns."""
    lines: list[str] = []
    for name, raw in providers.items():
        slot = raw if isinstance(raw, dict) else {}
        shown = safe_text(str(name))
        title = f"{shown} (manager, current)" if name == manager else shown
        host = host_text(slot)
        if name in named:
            host = f"{host} {NAMED}"
        details = [
            f"adapter: {safe_text(str(slot.get('adapter', '')))}",
            f"model: {safe_text(str(slot.get('model', '')))}",
            f"host: {host}",
            f"capabilities: {CAPABILITY_HINT}",
            price_text(slot),
        ]
        lines += textwrap.wrap(title, width=width, break_long_words=True)
        for detail in details:
            lines += textwrap.wrap(
                detail,
                width=width,
                initial_indent="  ",
                subsequent_indent="      ",
                break_long_words=True,
                break_on_hyphens=False,
            )
    return lines
