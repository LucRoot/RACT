"""Facts for the turn summary that the harness, not the model, reports (B-038).

LR:: A model's closing sentence is a claim. Published records of agent
runs find many "all tests pass" endings where the tests did not pass, and
RACT's intent is that the model never decides it is done. The summary is
assembled from what RACT observed: the files it changed and by how many
lines, whether it ran a verifier, and the model's own claims that nothing
verified. The claim check is a short pattern list, deliberately
conservative: it flags a reply that says tests pass in a turn where RACT
ran none, and nothing else.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

# A reply that says these things makes a claim only a verifier run can back.
CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "tests pass",
        re.compile(
            r"\b(?:all\s+(?:the\s+)?)?tests?\s+(?:now\s+)?pass(?:es|ed|ing)?\b", re.I
        ),
    ),
    (
        "tests pass",
        re.compile(
            r"\bpass(?:es|ed)?\s+(?:all\s+(?:the\s+)?)?(?:\d+\s+)?tests?\b", re.I
        ),
    ),
    (
        "verified",
        re.compile(r"\b(?:I\s+(?:have\s+)?)?verified\s+(?:that|it|the)\b", re.I),
    ),
    ("tested", re.compile(r"\b(?:fixed|done)\s+and\s+tested\b", re.I)),
)


# Words before a match, in the same sentence, that make it an instruction,
# a condition or a negation instead of a claim ("run pytest to check that
# the tests pass", "until the tests pass", "the tests do not pass").
_NOT_A_CLAIM = re.compile(
    r"\b(?:check|checks|ensure|make sure|verify|confirm|whether|if|until|should|"
    r"to see|expect|once|when|not|n't|never|fail\w*|run|rerun)\b",
    re.I,
)


def unverified_claims(text: str) -> list[str]:
    """Distinct claims in ``text`` that a verifier run would have to back."""
    found: list[str] = []
    for name, pattern in CLAIM_PATTERNS:
        if name in found:
            continue
        for match in pattern.finditer(text):
            sentence_start = max(
                text.rfind(".", 0, match.start()),
                text.rfind("\n", 0, match.start()),
                text.rfind("!", 0, match.start()),
                text.rfind("?", 0, match.start()),
            )
            before = text[sentence_start + 1 : match.start()]
            if not _NOT_A_CLAIM.search(before):
                found.append(name)
                break
    return found


def _lines(data: bytes) -> list[str] | None:
    try:
        return data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


def diffstat(
    project: Path, paths: list[str], before: Path | None, saved: set[str]
) -> dict[str, dict[str, Any]]:
    """Lines added and removed per changed path, by this turn only.

    LR:: The previous bytes of every file the turn replaced are in the
    turn's backup (``before``, holding ``saved``), so the count is exactly
    what RACT changed. Comparing with git HEAD also counted the operator's
    own uncommitted edits to the same file and did not work outside a git
    repository (G-059). A path with no backup was created by the turn and
    counts as ``new``; a backed-up path that is gone counts as ``deleted``.
    """
    stats: dict[str, dict[str, Any]] = {}
    for path in paths:
        full = project / path
        try:
            after = full.read_bytes() if full.is_file() else None
            old = (
                (before / path).read_bytes()
                if before is not None and path in saved
                else None
            )
        except OSError as exc:
            print(f"note: could not count changed lines in {path}: {exc}", flush=True)
            continue
        if old is None:
            if after is not None:
                new_lines = _lines(after)
                stats[path] = (
                    {"binary": True} if new_lines is None else {"new": len(new_lines)}
                )
            continue
        if after is None:
            stats[path] = {"deleted": True}
            continue
        old_lines, new_lines = _lines(old), _lines(after)
        if old_lines is None or new_lines is None:
            stats[path] = {"binary": True}
            continue
        added = removed = 0
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
        stats[path] = {"added": added, "removed": removed}
    return stats


def describe_change(path: str, stat: dict[str, Any] | None) -> str:
    """``src/calc.py (+1 -1)``, ``notes.md (new, 12 lines)``."""
    if not stat:
        return path
    if stat.get("binary"):
        return f"{path} (binary)"
    if stat.get("deleted"):
        return f"{path} (deleted)"
    if "new" in stat:
        return f"{path} (new, {stat['new']} lines)"
    return f"{path} (+{stat.get('added', 0)} -{stat.get('removed', 0)})"


__all__ = ["CLAIM_PATTERNS", "describe_change", "diffstat", "unverified_claims"]
