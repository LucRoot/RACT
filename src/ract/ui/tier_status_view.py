"""The tier-3 status line and the grant expiry notice as text (B-111, ADR-0048 D3).

Pure: no import from the event layer or the policy loader, no read of a key or a file,
no event emitted. The policy loader (the BUILDER's, not yet built) fills a TierState;
this module says it in words. The wording is ADR-0048 D3's:
  T3 off (no grant) | T3 off (grant expired <date>) | T3 ask | T3 allowlist |
  UNRESTRICTED (signed grant) | T3 suspended: policy changed
A grant that expires within seven days adds one notice at session start.

Plain text by default. ``rich=True`` marks the two states that must not be missed
(UNRESTRICTED and suspended) with bold markup; the caller prints it through the
console's markup. Nothing here writes an escape sequence, so NO_COLOR and plain mode
get the same words.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

Mode = Literal["off", "ask", "allowlist", "unrestricted"]

NOTICE_WINDOW_DAYS = 7


@dataclass(frozen=True)
class TierState:
    """What the policy loader reports. ``grant_expires`` is set when a grant exists."""

    mode: Mode = "off"
    grant_expires: date | None = None
    suspended: bool = False


def _text(state: TierState, today: date | None) -> str:
    if state.suspended:
        return "T3 suspended: policy changed"
    if state.mode == "unrestricted":
        return "UNRESTRICTED (signed grant)"
    if state.mode == "ask":
        return "T3 ask"
    if state.mode == "allowlist":
        return "T3 allowlist"
    if (
        state.grant_expires is not None
        and today is not None
        and state.grant_expires < today
    ):
        return f"T3 off (grant expired {state.grant_expires.isoformat()})"
    return "T3 off (no grant)"


def status_line(
    state: TierState, today: date | None = None, *, rich: bool = False
) -> str:
    """The status-line item for the tier, e.g. ``T3 ask``."""
    text = _text(state, today)
    if rich and (state.suspended or state.mode == "unrestricted"):
        return f"[bold]{text}[/bold]"
    return text


def expiry_notice(state: TierState, today: date) -> str | None:
    """One notice when a signed grant expires within the next seven days, else None."""
    if state.grant_expires is None:
        return None
    days = (state.grant_expires - today).days
    if days < 0 or days > NOTICE_WINDOW_DAYS:
        return None
    if days == 0:
        when = "today"
    elif days == 1:
        when = "tomorrow"
    else:
        when = f"in {days} days"
    return (
        f"notice: the signed grant expires {when} ({state.grant_expires.isoformat()}); "
        "sign it again before then"
    )
