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

import re
import subprocess
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


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=project, capture_output=True, text=True, timeout=30
    )


def diffstat(project: Path, paths: list[str]) -> dict[str, dict[str, Any]]:
    """Lines added and removed per changed path, against HEAD.

    A path git does not know (a new, untracked file) reports its line
    count as ``new``; a path that no longer exists reports ``deleted``.
    One ``git diff --numstat`` for all paths; empty when git is absent.
    """
    if not paths:
        return {}
    stats: dict[str, dict[str, Any]] = {}
    try:
        out = _git(project, "diff", "--numstat", "HEAD", "--", *paths)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"note: could not count changed lines: {exc}", flush=True)
        return {}
    if out.returncode == 0:
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                added, removed, path = parts
                stats[path] = (
                    {"binary": True}
                    if added == "-"
                    else {"added": int(added), "removed": int(removed)}
                )
    for path in paths:
        if path in stats:
            continue
        full = project / path
        if not full.exists():
            stats[path] = {"deleted": True}
        elif full.is_file():
            try:
                lines = full.read_bytes().count(b"\n")
            except OSError:
                continue
            stats[path] = {"new": lines}
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
