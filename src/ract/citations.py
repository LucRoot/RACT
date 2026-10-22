"""Check the file and line citations in a model's answer (B-037a).

A pure module: ``extract`` finds the citations in the text, and ``verify``
checks each one against the repository. The model's text is hostile input.
Every path in it is resolved through ``ract.workspace_path``, a file is read
only after it passes that check, and at most ``MAX_CHECKED`` citations are
checked per answer. The result strings carry the path and the symbol only,
never file content, and they pass through ``safe_text``.

The symbol check is a substring match: the symbol must appear as text in the
cited lines. It does not parse the code, so a name inside a comment counts.
A bare name with no separator and no extension (``x:1``) is not a citation.

The turn summary that shows the counts is a later card (B-037b).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ract.session_events import safe_text
from ract.workspace_path import resolve_workspace_path

MAX_CHECKED = 50
# A line number this large is not checked: its text is never converted to an int.
TOO_LARGE_LINE = 10**10
MAX_FILE_BYTES = 2 * 1024 * 1024
# Top-level names that are never opened, whatever the resolver says.
_NEVER_OPENED_TOP = frozenset({".git", ".ract", ".rack"})

# A path is one of: a dotted file name (x.py, README.md), a dotfile (.env), or a
# name with at least one separator (src/app/x, ../etc/passwd, C:\Windows\x).
# The separator form is what lets hostile paths be seen and refused. A path that
# follows a slash, a colon, a dot or a backslash is part of something else (a URL,
# a longer name), and is skipped.
_SEG = r"[\w.-]+"
_PREFIX = r"(?:[A-Za-z]:|\.{1,2})?[/\\]?"
_NAME_EXT = _SEG + r"\.[A-Za-z][A-Za-z0-9]{0,7}"
_DOTFILE = r"\.[A-Za-z][\w-]*"
_WITH_SEP = r"(?:" + _SEG + r"[/\\])+" + _SEG
_PATH = _PREFIX + r"(?:" + _NAME_EXT + r"|" + _WITH_SEP + r"|" + _DOTFILE + r")"
_CITE_RE = re.compile(
    r"(?<![\w/.:\\-])(?P<path>" + _PATH + r")"
    r":(?P<start>\d+)(?:-(?P<end>\d+)|,(?P<second>\d+))?(?![\d/\w])"
)
_BACKTICK_LINE_RE = re.compile(
    r"`(?P<path>" + _PATH + r")`\s+line\s+(?P<start>\d+)(?:-(?P<end>\d+))?"
)
_SPAN_RE = re.compile(r"`([^`\n]{1,120})`")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Citation:
    path: str
    start: int
    end: int
    symbol: str | None
    position: int


@dataclass(frozen=True)
class Result:
    citation: Citation
    status: str  # "verified", "unverified" or "not checked"
    reason: str


def _symbol_before(text: str, position: int) -> str | None:
    """The last backticked identifier in the same sentence, before *position*."""
    chunk = text[max(0, position - 160) : position]
    sentence = re.split(r"[.!?\n]", chunk)[-1]
    spans = list(_SPAN_RE.finditer(sentence))
    for span in reversed(spans):
        inner = span.group(1).strip()
        if _IDENT_RE.fullmatch(inner):
            return inner
    return None


def _line_number(digits: str) -> int:
    """The line number in *digits*. Anything over nine digits is TOO_LARGE_LINE."""
    if len(digits) > 9:
        return TOO_LARGE_LINE
    return int(digits)


def extract(text: str) -> list[Citation]:
    """Every citation in *text*, in order of appearance."""
    found: list[Citation] = []
    for match in _CITE_RE.finditer(text):
        start = _line_number(match.group("start"))
        if match.group("end") is not None:
            end = _line_number(match.group("end"))
        elif match.group("second") is not None:
            end = _line_number(match.group("second"))
        else:
            end = start
        found.append(
            Citation(
                path=match.group("path"),
                start=start,
                end=end,
                symbol=_symbol_before(text, match.start()),
                position=match.start(),
            )
        )
    for match in _BACKTICK_LINE_RE.finditer(text):
        start = _line_number(match.group("start"))
        end = _line_number(match.group("end")) if match.group("end") else start
        found.append(
            Citation(
                path=match.group("path"),
                start=start,
                end=end,
                symbol=_symbol_before(text, match.start()),
                position=match.start(),
            )
        )
    found.sort(key=lambda c: c.position)
    return found


def _read_capped(path: Path) -> bytes:
    """Read a regular file that already passed the checks and the size cap."""
    return path.read_bytes()


def _check_one(root: Path, citation: Citation) -> Result:
    path = safe_text(citation.path)
    if max(citation.start, citation.end) >= TOO_LARGE_LINE:
        return Result(citation, "not checked", f"{path}: line number too large")
    top = citation.path.replace("\\", "/").split("/", 1)[0]
    if top in _NEVER_OPENED_TOP:
        return Result(citation, "not checked", f"{path} is protected, not checked")
    resolved = resolve_workspace_path(root, citation.path, purpose="send")
    if not resolved.is_ok():
        return Result(
            citation,
            "not checked",
            f"{path} is protected or outside the project, not checked",
        )
    target = resolved.unwrap()
    if os.path.islink(target):
        return Result(citation, "not checked", f"{path} is a link, not checked")
    if not target.exists():
        return Result(citation, "unverified", f"no such file: {path}")
    if target.is_dir():
        return Result(citation, "unverified", f"{path} is a directory, not a file")
    if target.stat().st_size > MAX_FILE_BYTES:
        return Result(citation, "unverified", f"{path} is too large to check")
    text = _read_capped(target).decode("utf-8", errors="replace")
    lines = text.splitlines()
    count = len(lines)
    if citation.start < 1:
        return Result(citation, "unverified", f"line {citation.start} does not exist")
    if citation.end < citation.start:
        return Result(
            citation,
            "unverified",
            f"the range {citation.start}-{citation.end} is reversed",
        )
    if citation.end > count:
        return Result(
            citation,
            "unverified",
            f"{path} has {count} lines; line {citation.end} does not exist",
        )
    if citation.symbol is not None:
        cited = "\n".join(lines[citation.start - 1 : citation.end])
        if citation.symbol not in cited:
            symbol = safe_text(citation.symbol)
            return Result(
                citation,
                "unverified",
                f"symbol {symbol} is not in lines {citation.start}-{citation.end}",
            )
    return Result(citation, "verified", f"lines {citation.start}-{citation.end} exist")


def verify(root: Path | str, citations: list[Citation]) -> list[Result]:
    """Check each citation, in order. Only the first MAX_CHECKED are checked."""
    base = Path(root)
    results: list[Result] = []
    for index, citation in enumerate(citations):
        if index >= MAX_CHECKED:
            results.append(
                Result(citation, "not checked", "too many citations to check")
            )
            continue
        results.append(_check_one(base, citation))
    return results


__all__ = ["Citation", "Result", "extract", "verify", "MAX_CHECKED", "MAX_FILE_BYTES"]
