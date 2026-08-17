"""CI gate against shipping a stale/broken demo.cast.

Verifies:
 - The asciicast is a valid v2 file (header + JSONL event frames).
 - It has at least a few event frames (not truncated to empty).
 - Every ``ract <verb>`` invocation in the cast references a current
   CLI verb (in ``CLI_VERBS``). Adding or renaming a verb without
   re-recording the demo fails this gate.

The cast's operator-side path leaks (noted in earlier audits, deferred
to v0.4.0-final) are a separate concern; this test enforces FRESHNESS
of the commands only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ract.cli import CLI_VERBS


REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_CAST = REPO_ROOT / "assets" / "demo.cast"

# Match a shell invocation of ract: a shell prompt token (``$`` or
# ``>``) preceding ``ract <verb>``. Case-sensitive lowercase-only so
# prose lines like "RACT demo:" or "RACT keeps" do not match. Long-
# option flags following ``ract`` are skipped in the caller.
_VERB_RE = re.compile(r"(?:\$|>)\s+ract\s+([a-z][a-z0-9-]*)")


def _parse_cast() -> tuple[dict, list[list]]:
    """Return (header, events) for the v2 asciicast at ``DEMO_CAST``."""
    text = DEMO_CAST.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "demo.cast is empty"
    header = json.loads(lines[0])
    events = [json.loads(line) for line in lines[1:]]
    return header, events


def test_demo_cast_parses() -> None:
    """demo.cast loads as valid v2 asciicast (header + JSONL events)."""
    header, events = _parse_cast()
    assert header.get("version") == 2, f"expected v2, got {header.get('version')!r}"
    # Every event is a triple [time, kind, data].
    for event in events:
        assert isinstance(event, list) and len(event) == 3, (
            f"malformed event frame: {event!r}"
        )


def test_demo_cast_has_events() -> None:
    """At least three event frames present."""
    _header, events = _parse_cast()
    assert len(events) >= 3, f"only {len(events)} event frames — cast is truncated"


def test_demo_cast_commands_are_current_cli_verbs() -> None:
    """Every ract <verb> invocation resolves to a current CLI_VERBS entry."""
    _header, events = _parse_cast()
    payload = "".join(str(event[2]) for event in events if event[1] == "o")

    verb_hits: set[str] = set()
    for match in _VERB_RE.finditer(payload):
        raw = match.group(1)
        # Long-option flags following "ract" are not verbs.
        if raw.startswith("-"):
            continue
        verb_hits.add(raw.lower())

    current = {v.lower() for v in CLI_VERBS}
    stale = sorted(verb_hits - current)
    assert not stale, (
        f"demo.cast references stale/renamed verbs {stale}; current "
        f"CLI_VERBS has: {sorted(current)}"
    )


# RACT 0.4.1
