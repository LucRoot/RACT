"""The reasoning effort setting: off by default, mapped per provider (B-057).

A session can ask a reasoning-capable model to think less or more with
``/set reasoning <value>``. With the setting off, no request carries a
reasoning field. With a value set, a provider that has a documented setting
for it gets that field on each request; any other provider gets its request
unchanged and one line that says the setting is ignored.

The config key ``reasoning_effort`` waits for the BUILDER's approval (B-057
ESCALATE), so only the session setting exists here.

Mapping status: the OpenAI-style ``reasoning_effort`` field is sent only to
the OpenAI endpoint. The repository docs do not describe that field, so the
mapping is marked unverified in docs/PROVIDER_SETUP.md. Other providers are
not mapped.
"""

from __future__ import annotations

import sys
from typing import Any
from urllib.parse import urlsplit

EFFORT_LEVELS = ("off", "low", "medium", "high")
FIELD = "reasoning_effort"
# Hosts whose documented request format takes the field. See the module note.
MAPPED_HOSTS = frozenset({"api.openai.com"})

_session_effort = "off"
_noted: set[str] = set()


def session_effort() -> str:
    """The value the session set with ``/set reasoning``. Starts as ``off``."""
    return _session_effort


def set_session_effort(value: str) -> None:
    """Set the session value. Raises ValueError with the valid list when wrong."""
    global _session_effort
    cleaned = value.strip().lower()
    if cleaned not in EFFORT_LEVELS:
        raise ValueError(
            f"reasoning takes one of: {', '.join(EFFORT_LEVELS)}"
        )
    _session_effort = cleaned


def reset_session_effort() -> None:
    """Back to ``off``, and forget which providers were already noted."""
    global _session_effort
    _session_effort = "off"
    _noted.clear()


def apply(payload: dict[str, Any], *, url: str, provider: str) -> dict[str, Any]:
    """Return the request payload with the reasoning field when it applies.

    The payload is changed only in the field this module owns. A provider
    without a mapping gets its payload back unchanged, and the note is printed
    once per provider for the session.
    """
    effort = _session_effort
    if effort == "off":
        return payload
    host = urlsplit(url).hostname or ""
    if host in MAPPED_HOSTS:
        return {**payload, FIELD: effort}
    if provider not in _noted:
        _noted.add(provider)
        print(
            f"reasoning_effort is ignored by {provider}: it has no setting for it",
            file=sys.stderr,
            flush=True,
        )
    return payload
