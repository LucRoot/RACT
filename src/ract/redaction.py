"""Redact secret-shaped values from text before it is shown or streamed.

LR:: Session events promise that no event carries a key or a token
(docs/EVENTS_SESSION.md). Model text and operator input can contain one,
for example when a file the operator asked about holds a key. ``redact``
replaces known secret formats. ``StreamingRedactor`` does the same for text
that arrives in pieces: a key split across two deltas matches neither piece
alone, so the redactor holds back the tail of each piece until the next one
arrives or the message ends.

The pattern list is deliberately small and specific, so ordinary code and
prose pass unchanged. The request-body scanner (S-022) will extend it.
"""

from __future__ import annotations

import re

REPLACEMENT = "[redacted]"

# Longer than any single-line format below needs to become recognisable;
# docs/EVENTS_SESSION.md states this number.
HOLD_BACK_CHARS = 128

_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[\s\S]*\Z)",
        r"\bsk-[A-Za-z0-9_-]{16,}",
        r"\bgh[pousr]_[A-Za-z0-9]{20,}",
        r"\bgithub_pat_[A-Za-z0-9_]{20,}",
        r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\bAIza[0-9A-Za-z_-]{35}",
        r"\bhf_[A-Za-z0-9]{30,}",
        r"\bnvapi-[A-Za-z0-9_-]{20,}",
        r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*",
        # user:password in a URL; the scheme and host stay readable.
        r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)",
    )
)


def redact(text: str) -> str:
    """Return ``text`` with every secret-shaped value replaced."""
    for pattern in _PATTERNS:
        text = pattern.sub(REPLACEMENT, text)
    return text


class StreamingRedactor:
    """Redacts text that arrives in pieces.

    ``feed`` returns the part of the text that is safe to emit now;
    ``close`` returns the rest. Text is emitted only when it is at least
    ``hold_back`` characters from the end of what has arrived, and never in
    the middle of a match. A match that reaches the end of the buffer may
    still be growing (a token whose last characters have not arrived), so
    everything from its start is held.
    """

    def __init__(self, hold_back: int = HOLD_BACK_CHARS) -> None:
        self._hold_back = hold_back
        self._buffer = ""

    def feed(self, piece: str) -> str:
        self._buffer += piece
        text = self._buffer
        cut = max(0, len(text) - self._hold_back)
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                if match.start() < cut < match.end() or match.end() >= len(text):
                    cut = min(cut, match.start())
        self._buffer = text[cut:]
        return redact(text[:cut])

    def close(self) -> str:
        text, self._buffer = self._buffer, ""
        return redact(text)
