"""The model's context window, when something measured or declared it (B-084).

LR:: ``session.started`` used to send ``context_limit: null`` always. The
window is now the probe's measured ``usable_context_window`` when the
capability record exists (``ract`` writes it under ``.ract/probes/``), else
the ``context_window`` the provider's entry in ``ract.yaml`` declares, else
null: RACT does not guess a size.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


def context_limit(
    project: Path | str, provider_config: dict[str, Any] | None
) -> int | None:
    """The context window for this session's model, or None when nothing says it."""
    from ract.memory.probes.scheduler import read_capability_record

    try:
        record = read_capability_record(Path(project))
    except ValueError as exc:
        print(f"[context] the capability record cannot be read: {exc}", file=sys.stderr)
        record = None
    measured = getattr(record, "usable_context_window", None)
    if isinstance(measured, int) and measured > 0:
        return measured
    declared = (provider_config or {}).get("context_window")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0:
        return declared
    return None


__all__ = ["context_limit"]
