"""Last-line secret scan on everything RACT sends to a provider (S-022).

LR:: S-018 keeps known secret paths (``.env``, ``.git/``, ``.ract/``, key
files) out of model requests. A secret can still sit inside a file the
operator legitimately asked about, in a test log fed back to the model, or
in the text the operator typed. Every serialized request therefore passes
this scan just before it leaves: secret-shaped values are replaced with
``[redacted]`` and one notice names the patterns and counts, never the
values. The model does not need a key to reason about the code around it.

Redacting is safe for context, but not for the file a step rewrites: the
model would return the file with the placeholder and the write would
replace the real key. ``Executor._target_file_block`` refuses that step
before any request is made (``target_holds_secret``).

The pattern list is ``ract.redaction.NAMED_PATTERNS``, shared with the
session-event redactor so the two cannot drift.
"""

from __future__ import annotations

import sys
from typing import Any

from ract import turn_context
from ract.redaction import redact_report


def _merge(into: dict[str, int], counts: dict[str, int]) -> None:
    for name, n in counts.items():
        into[name] = into.get(name, 0) + n


def scan_messages(messages: list[Any]) -> tuple[list[Any], dict[str, int]]:
    """Return a redacted copy of chat ``messages`` and the counts by pattern.

    String ``content`` and the ``text`` of list-form content parts are
    scanned; other fields (roles, tool ids) pass unchanged.
    """
    counts: dict[str, int] = {}
    cleaned: list[Any] = []
    for message in messages:
        if not isinstance(message, dict):
            cleaned.append(message)
            continue
        out = dict(message)
        content = message.get("content")
        if isinstance(content, str):
            out["content"], found = redact_report(content)
            _merge(counts, found)
        elif isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    part = dict(part)
                    part["text"], found = redact_report(part["text"])
                    _merge(counts, found)
                parts.append(part)
            out["content"] = parts
        cleaned.append(out)
    return cleaned, counts


# Keys whose values are fixed vocabulary or identifiers, never content.
_VOCABULARY_KEYS = frozenset({"role", "model", "id", "type", "tool_call_id", "object"})


def scan_payload(payload: Any) -> tuple[Any, dict[str, int]]:
    """Return a redacted copy of a whole request payload and the counts.

    LR:: Scanning only ``messages[].content`` missed secrets in an assistant
    message's ``tool_calls[].function.arguments`` (every agent-loop turn),
    in a completions-style ``prompt`` and in a ``system`` string (G-030).
    Every string leaf is scanned except the values of fixed-vocabulary keys
    and a tool's ``name``.
    """
    counts: dict[str, int] = {}

    def walk(value: Any, key: str | None, parent_is_function: bool) -> Any:
        if isinstance(value, str):
            if key in _VOCABULARY_KEYS or (key == "name" and parent_is_function):
                return value
            cleaned, found = redact_report(value)
            _merge(counts, found)
            return cleaned
        if isinstance(value, dict):
            is_function = "arguments" in value or "parameters" in value
            return {k: walk(v, k, is_function) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key, False) for v in value]
        return value

    return walk(payload, None, False), counts


def scan_text(text: str) -> tuple[str, dict[str, int]]:
    """Redact one outbound string (a search query, a subprocess's stdin)."""
    return redact_report(text)


def describe(counts: dict[str, int]) -> str:
    """``"2 OpenAI-style key, 1 secret assignment"``: names and counts only."""
    return ", ".join(f"{n} {name}" for name, n in sorted(counts.items()))


def notify(counts: dict[str, int], destination: str) -> None:
    """Tell the operator what was redacted from a request to ``destination``.

    In a session the notice is a session event; otherwise it goes to stderr,
    so stdout stays the answer (headless output discipline).
    """
    if not counts:
        return
    text = (
        f"redacted secret-shaped values before sending to {destination}: "
        f"{describe(counts)}. The values were not sent."
    )
    if turn_context.has_reporter():
        turn_context.report("notice", {"level": "warning", "text": text})
        return
    print(f"note: {text}", file=sys.stderr, flush=True)


def target_holds_secret(text: str) -> dict[str, int]:
    """Counts of secret-shaped values in a step's target file (empty if none)."""
    return redact_report(text)[1]
