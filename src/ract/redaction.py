"""Redact secret-shaped values from text before it is shown or streamed.

LR:: Session events promise that no event carries a key or a token
(docs/EVENTS_SESSION.md). Model text and operator input can contain one,
for example when a file the operator asked about holds a key. ``redact``
replaces known secret formats. ``StreamingRedactor`` does the same for text
that arrives in pieces: a key split across two deltas matches neither piece
alone, so the redactor holds back the incomplete last token of each piece
until the next one arrives or the message ends.

The pattern list is deliberately small and specific, so ordinary code and
prose pass unchanged. The request-body scanner (S-022) will extend it.
"""

from __future__ import annotations

import re

REPLACEMENT = "[redacted]"

# The longest trailing token the streaming redactor holds back. A longer
# token releases its head; the last 128 characters stay held, which covers
# every single-line format below.
HOLD_BACK_CHARS = 128

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")

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

# A token after one of these is a credential even though whitespace
# separates them, so the two are held together.
_HOLD_WITH_NEXT = re.compile(r"(?i)(?:\bbearer|authorization:)\s*\Z")


def redact(text: str) -> str:
    """Return ``text`` with every secret-shaped value replaced."""
    for pattern in _PATTERNS:
        text = pattern.sub(REPLACEMENT, text)
    return text


class StreamingRedactor:
    """Redacts text that arrives in pieces, holding back as little as it can.

    ``feed`` returns the part of the text that is safe to emit now;
    ``close`` returns the rest. Everything up to the last whitespace is
    released at once, because the secret formats contain no whitespace;
    only the trailing incomplete token is held (at most ``hold_back``
    characters of it). Prose therefore lags by about one word, which keeps
    a slow local model's text visible as it arrives (G-026: a fixed
    128-character hold-back lagged 3 to 8 s at 4 to 10 tokens/s).

    Two shapes span whitespace: ``Bearer <token>`` and ``Authorization:
    <token>`` hold the keyword with the token, and a private-key block is
    replaced once at its BEGIN line and everything up to its END line is
    dropped, however long it is. A release point never falls inside a
    match.
    """

    def __init__(self, hold_back: int = HOLD_BACK_CHARS) -> None:
        self._hold_back = hold_back
        self._buffer = ""
        self._in_key_block = False

    def feed(self, piece: str) -> str:
        out: list[str] = []
        self._buffer += piece
        while True:
            if self._in_key_block:
                end = _PEM_END.search(self._buffer)
                if end is None:
                    # Keep only enough to recognise an END line split
                    # across pieces; the key body is never released.
                    self._buffer = self._buffer[-64:]
                    return "".join(out)
                self._buffer = self._buffer[end.end() :]
                self._in_key_block = False
                continue
            begin = _PEM_BEGIN.search(self._buffer)
            if begin is None:
                break
            out.append(redact(self._buffer[: begin.start()]) + REPLACEMENT)
            self._buffer = self._buffer[begin.end() :]
            self._in_key_block = True
        out.append(self._release())
        return "".join(out)

    def _release(self) -> str:
        text = self._buffer
        # Release up to and including the last whitespace character.
        cut = 0
        for i in range(len(text) - 1, -1, -1):
            if text[i].isspace():
                cut = i + 1
                break
        if len(text) - cut > self._hold_back:
            cut = len(text) - self._hold_back
        # A keyword that makes the next token a credential is held with it.
        keyword = _HOLD_WITH_NEXT.search(text[:cut])
        if keyword is not None:
            cut = keyword.start()
        # A BEGIN line contains spaces ("-----BEGIN RSA PRIVATE KEY-----"),
        # so hold an unfinished one until its line ends: it may be a key.
        begin_line = text.rfind("-----BEGIN")
        if begin_line != -1 and "\n" not in text[begin_line:]:
            cut = min(cut, begin_line)
        # Never release part of a match.
        for pattern in _PATTERNS:
            for match in pattern.finditer(text):
                if match.start() < cut < match.end():
                    cut = match.start()
        self._buffer = text[cut:]
        return redact(text[:cut])

    def close(self) -> str:
        if self._in_key_block:
            self._buffer, self._in_key_block = "", False
            return ""
        text, self._buffer = self._buffer, ""
        return redact(text)

    @property
    def held(self) -> int:
        """Characters received and not yet released."""
        return len(self._buffer)
