"""What /context says about the session (B-032b). Pure: no I/O and no request.

The numbers come from the egress ledger's records (what the server reported,
when it reported it) and from a window the server gave, if any. A value that
is not reported is shown as "not reported", and a window that is not known is
shown as "unknown". No character-based estimate is shown.
"""

from __future__ import annotations

from ract.cell_wrap import wrap_cells
from typing import Any

from ract.session_events import safe_text


def _host(record: dict[str, Any]) -> str:
    return safe_text(str(record.get("host") or "unknown host"))


def context_lines(
    records: list[dict[str, Any]], window: int | None, *, width: int = 80
) -> list[str]:
    """The plain-words lines for /context, each wrapped to ``width`` columns."""
    lines: list[str] = []
    if not records:
        lines.append("no model request has been sent from this machine yet")
    else:
        last = records[-1]
        host = _host(last)
        tokens_in, tokens_out = last.get("tokens_in"), last.get("tokens_out")
        if tokens_in is None and tokens_out is None:
            lines.append(f"last request on this machine: sizes not reported by {host}")
        else:
            lines.append(
                f"last request on this machine used {tokens_in or 0} tokens in, "
                f"{tokens_out or 0} out (reported by {host})"
            )
    if window:
        lines.append(f"window is {window} tokens (from the server)")
    else:
        lines.append(
            "window: unknown (RACT does not keep what the provider probe measured yet)"
        )
    lines.append("turns: not stored in the session file")
    lines.append(
        "the next request is built per step; its size is not known until it is sent"
    )
    out: list[str] = []
    for line in lines:
        # By terminal columns (package O): a wide host name is two columns a character.
        out.extend(wrap_cells(line, width, subsequent_indent="  ") or [""])
    return out
