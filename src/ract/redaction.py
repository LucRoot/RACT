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

Known values (V7-05): a pattern cannot know a key that has no telltale
shape. When a provider key is resolved, ``register_known`` keeps its exact
value and its URL-encoded and base64 forms in this process's memory, and
``redact`` and ``StreamingRedactor`` mask them like a pattern match. They are
never written anywhere; a value shorter than 8 characters is not kept.
"""

from __future__ import annotations

import base64
import re
import threading
from typing import Any
from urllib.parse import quote

REPLACEMENT = "[redacted]"

# The longest trailing token the streaming redactor holds back. A longer
# token releases its head; the last 128 characters stay held, which covers
# every single-line format below.
HOLD_BACK_CHARS = 128

_PEM_BEGIN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_PEM_END = re.compile(r"-----END [A-Z0-9 ]*PRIVATE KEY-----")

# A variable or field name that says it holds a credential: a separated
# word (api_key, client-secret, DB_PASSWORD, auth.token) in any case, or a
# camelCase one (apiKey, clientSecret). "author", "tokenizer" and "monkey"
# are not names of this kind.
_REFERENCE_SUFFIXES = (
    "id", "ids", "name", "names", "file", "filename", "path", "env", "var",
    "url", "type", "size", "len", "length", "count", "prefix", "suffix",
    "header", "field", "label", "format", "kind", "dir", "hash",
)  # fmt: skip
_NOT_A_REFERENCE = "".join(
    rf"(?<!(?i:[_.-]{suffix}))(?<!{suffix.capitalize()})"
    for suffix in _REFERENCE_SUFFIXES
)
_SECRET_NAME = (
    r"(?!(?i:public))"
    r"(?:(?i:(?:[a-z0-9]+[_.-])*"
    r"(?:api[_-]?key|key|token|secret|passw(?:or)?d|pwd|credentials?|auth)"
    r"(?:[_.-][a-z0-9]+)*)"
    r"|[a-z][a-zA-Z0-9]*(?:Key|Token|Secret|Password|Passwd|Credentials?|Auth)"
    r"[A-Za-z0-9]*)" + _NOT_A_REFERENCE
)
_PASSWORD_NAME = (
    r"(?:(?i:(?:[a-z0-9]+[_.-])*(?:passw(?:or)?d|passphrase|secret)"
    r"(?:[_.-][a-z0-9]+)*)"
    r"|[a-z][a-zA-Z0-9]*(?:Password|Passphrase|Secret)[A-Za-z0-9]*)" + _NOT_A_REFERENCE
)
# Values that are references or placeholders, never secrets.
_NOT_A_VALUE = (
    r"(?![$<]|os\.|getenv|process\.env|\[redacted\]"
    r"|(?i:your[-_ ]|change[-_]?me|example|placeholder|x{4}|dummy))"
)

# (name, pattern). The name is what a notice reports; the value never is.
# A pattern with a group named ``keep`` keeps that part (the variable name,
# the opening quote, the URL parameter) and replaces the rest of the match.
NAMED_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(p))
    for name, p in (
        (
            "private key block",
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[\s\S]*\Z)",
        ),
        ("OpenAI-style key", r"\bsk-[A-Za-z0-9_-]{16,}"),
        ("Stripe-style key", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"),
        ("GitHub token", r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
        ("GitHub token", r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
        ("Slack token", r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
        ("Twilio key", r"\bSK[0-9a-f]{32}\b"),
        ("AWS access key id", r"\bAKIA[0-9A-Z]{16}\b"),
        ("Google API key", r"\bAIza[0-9A-Za-z_-]{35}"),
        ("Hugging Face token", r"\bhf_[A-Za-z0-9]{30,}"),
        ("NVIDIA API key", r"\bnvapi-[A-Za-z0-9_-]{20,}"),
        ("JWT", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        ("bearer token", r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}=*"),
        (
            "basic auth",
            r"(?P<keep>(?i:authorization:[ \t]*basic[ \t]+))[A-Za-z0-9+/]{12,}={0,2}",
        ),
        (
            "connection string key",
            r"(?P<keep>\b(?:AccountKey|SharedAccessKey)=)[A-Za-z0-9+/]{20,}={0,2}",
        ),
        # user:password in a URL; the scheme and host stay readable.
        ("URL credentials", r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),
        (
            "URL query secret",
            r"(?P<keep>[?&](?i:api[_-]?key|access[_-]?token|token|key|secret"
            r"|client[_-]?secret|password|passwd)=)[^&\s#\"'<>]{12,}",
        ),
        # NAME = "literal" in any language or config format, with any
        # separator and spacing; the value must be a quoted literal, so
        # `secret = load_secret(path)` is not matched.
        (
            "secret assignment",
            rf"(?P<keep>(?<![\w.-])(?:export[ \t]+)?[\"']?{_SECRET_NAME}[\"']?"
            rf"[ \t]*[:=][ \t]*[\"']){_NOT_A_VALUE}[^\s'\"]{{12,}}(?=[\"'])",
        ),
        # A passphrase has no digit (`password: correcthorsebatterystaple`),
        # so names that mean a password or secret (not key or token, where
        # `token: tokenizer` is common) also take one lowercase word of 12 or
        # more letters, not CamelCase and not followed by a call or a comma.
        (
            "secret assignment",
            rf"(?P<keep>(?<![\w.-])(?:export[ \t]+)?{_PASSWORD_NAME}(?:=|:[ \t]*))"
            rf"{_NOT_A_VALUE}[A-Za-z][a-z]{{11,}}+(?![\w.(,)=\[])",
        ),
        # NAME=value and NAME: value unquoted (.env, shell, YAML, query-ish
        # config). No space before the separator; the value contains a digit
        # and is not an identifier being called or indexed, so
        # `token=token_provider.get()` is not matched.
        (
            "secret assignment",
            rf"(?P<keep>(?<![\w.-])(?:export[ \t]+)?{_SECRET_NAME}(?:=|:[ \t]*))"
            rf"{_NOT_A_VALUE}(?=[^\s'\"]*\d)(?![A-Za-z_]\w*[.(\[])"
            # Possessive: the whole value is taken, so the annotation check
            # cannot be dodged by matching a shorter prefix.
            r"[^\s'\"#,;&(){}\[\]]{12,}+(?![ \t]*[,)=])",
        ),
    )
)
_PATTERNS: tuple[re.Pattern[str], ...] = tuple(p for _, p in NAMED_PATTERNS)


def _replace(match: re.Match[str]) -> str:
    keep = match.groupdict().get("keep")
    return (keep or "") + REPLACEMENT


# A token after one of these is a credential even though whitespace
# separates them, so the two are held together: Bearer, Basic, the
# Authorization header, and a credential name with its separator
# (`api_key: value`, `PASSWORD = "value"`).
_HOLD_WITH_NEXT = re.compile(
    rf"(?:(?i:authorization:[ \t]*(?:basic|bearer)?|\bbearer|\bbasic)"
    rf"|(?<![\w.-])[\"']?{_SECRET_NAME}[\"']?[ \t]*(?:[:=][ \t]*[\"']?)?)"
    rf"[ \t]*\Z"
)


KNOWN_MIN_LENGTH = 8
_known_lock = threading.Lock()
# The registered values and their encoded forms, longest first. Memory only.
_known: tuple[str, ...] = ()


def register_known(value: object) -> bool:
    """Mask *value* wherever text is redacted in this process (V7-05).

    Its URL-encoded form and its base64 forms (standard and URL-safe, with and
    without padding) are masked too. A value under 8 characters is not kept:
    masking it would hide ordinary words. True when the value was kept.
    """
    global _known
    if not isinstance(value, str) or len(value) < KNOWN_MIN_LENGTH:
        return False
    data = value.encode("utf-8")
    forms = {value, quote(value, safe="")}
    for encoded in (base64.b64encode(data), base64.urlsafe_b64encode(data)):
        text = encoded.decode("ascii")
        forms.update({text, text.rstrip("=")})
    with _known_lock:
        merged = set(_known) | {f for f in forms if len(f) >= KNOWN_MIN_LENGTH}
        _known = tuple(sorted(merged, key=len, reverse=True))
    return True


def clear_known() -> None:
    """Forget every registered value (tests, and a process that switches providers)."""
    global _known
    with _known_lock:
        _known = ()


def _mask_known(text: str) -> tuple[str, int]:
    count = 0
    for value in _known:
        if value in text:
            count += text.count(value)
            text = text.replace(value, REPLACEMENT)
    return text, count


def _hold_known(text: str, cut: int) -> int:
    """Move *cut* so no registered value is split and no released text ends with one's start."""
    moved = True
    while moved:
        moved = False
        for value in _known:
            start = text.find(value)
            while start != -1:
                if start < cut < start + len(value):
                    cut, moved = start, True
                start = text.find(value, start + 1)
            for size in range(min(len(value) - 1, cut), 0, -1):
                if text[cut - size : cut] == value[:size]:
                    cut, moved = cut - size, True
                    break
    return cut


def redact(text: str) -> str:
    """Return ``text`` with every secret-shaped value replaced."""
    return redact_report(text)[0]


def body(text: str, limit: int | None = 200) -> str:
    """A server's response body for an error line: redacted whole, then cut (B-165).

    LR:: A server that echoes the request's credentials in its error body
    (a 401 repeating the Authorization header) put the key into RACT's error
    text, and setup printed it (the wrong-key walk). Known values are
    matched whole, so the body is redacted before it is cut: cut first, a key
    at the cut would pass half masked. ``limit`` None keeps the whole body.
    """
    masked = redact(text)
    return masked if limit is None else masked[:limit]


def redact_report(text: str) -> tuple[str, dict[str, int]]:
    """Redact ``text`` and count the matches by pattern name."""
    counts: dict[str, int] = {}
    if _known:
        text, n = _mask_known(text)
        if n:
            counts["known_value"] = n
    for name, pattern in NAMED_PATTERNS:
        text, n = pattern.subn(_replace, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    return text, counts


class RedactingWriter:
    """A text stream that redacts each whole line before it reaches *target* (B-200).

    LR:: About thirty places print an error with ``print(..., file=sys.stderr)``
    or the console's stderr, each with the raw text of an exception or a
    provider's message. ``cli.main`` puts this in front of ``sys.stderr`` once,
    so every one of them is redacted, including the ones added later. A
    partial line waits for its end, or for ``flush``.
    """

    def __init__(self, target: Any) -> None:
        self._target = target
        self._pending = ""

    def write(self, text: str) -> int:
        self._pending += text
        *done, self._pending = self._pending.split("\n")
        for line in done:
            self._target.write(redact(line) + "\n")
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self._target.write(redact(self._pending))
            self._pending = ""
        self._target.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)


def redact_values(value: Any) -> Any:
    """*value* with every string in it redacted, at any depth (B-201)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_values(item) for item in value]
    return value


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
        # Nor part of a registered value (V7-05): a key split across deltas
        # is held until it can be masked whole.
        if _known:
            cut = _hold_known(text, cut)
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
