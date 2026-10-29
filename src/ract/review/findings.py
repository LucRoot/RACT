"""ReviewRequest, ReviewFindings and the finding validator (ADR-0049 D14, B-061a).

A REVIEWER's reply is model output about repository text, so it is hostile
input twice over. ``parse_findings`` accepts only the D14 shape: an object
with ``findings``, at most ``MAX_FINDINGS`` entries, each exactly ``path``,
``line``, ``severity``, ``claim`` and ``evidence``. There is no approval or
verdict field, so a reply cannot carry one. ``validate`` then checks every
finding against the repository through the B-037a citation verifier, which
resolves the path with ``resolve_workspace_path`` and never opens a protected
file or a link. What it drops it counts. Every text it keeps is printable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ract import citations
from ract.session_events import safe_text

MAX_FINDINGS = 20
MAX_CLAIM_CHARS = 300  # D-093 amendment 1: claims are short plain text
MAX_EVIDENCE_CHARS = 2000
SEVERITIES = ("defect", "risk", "note")
_FINDING_KEYS = frozenset({"path", "line", "severity", "claim", "evidence"})
# A finding's evidence may sit this many lines from the line it names.
_NEAR = 2


class FindingsRefused(ValueError):
    """A reply that is not a ReviewFindings object; the message says why."""


class _Malformed(ValueError):
    """One entry that is not a finding; it is dropped and counted."""


@dataclass(frozen=True)
class ReviewRequest:
    """What the harness sends the REVIEWER for one step (D14, item 1).

    The writer's reasoning, its prose, the chat history and any held-out
    predicate are not fields, so they cannot be sent.
    """

    step: int
    goal: str
    acceptance: tuple[str, ...]
    diff: str
    verification: str


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    severity: str
    claim: str
    evidence: str


@dataclass(frozen=True)
class ReviewFindings:
    findings: tuple[Finding, ...]
    # Findings past MAX_FINDINGS, entries that are not a finding (a missing
    # or extra key, a wrong type), and claims cut to MAX_CLAIM_CHARS.
    over_limit: int = 0
    malformed: int = 0
    claims_cut: int = 0


@dataclass
class ValidatedReview:
    """The findings that passed, with what was changed or dropped and why."""

    kept: list[Finding] = field(default_factory=list)
    downgraded: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    claims_cut: int = 0

    @property
    def dropped_total(self) -> int:
        return sum(self.dropped.values())


def _text(value: object, what: str, limit: int) -> tuple[str, bool]:
    if not isinstance(value, str):
        raise _Malformed(what)
    plain = " ".join(value.replace("\r\n", "\n").split()) if what == "claim" else value
    cut = len(plain) > limit
    return plain[:limit], cut


def parse_findings(data: object) -> ReviewFindings:
    """The ReviewFindings in *data* (a decoded JSON reply), or FindingsRefused."""
    if not isinstance(data, Mapping) or set(data) != {"findings"}:
        raise FindingsRefused("the reply is not an object with only 'findings'")
    raw = data["findings"]
    if not isinstance(raw, list):
        raise FindingsRefused("'findings' is not a list")
    findings: list[Finding] = []
    claims_cut = 0
    malformed = 0
    for entry in raw[:MAX_FINDINGS]:
        try:
            finding, cut = _finding(entry)
        except _Malformed:
            malformed += 1
            continue
        claims_cut += cut
        findings.append(finding)
    return ReviewFindings(
        tuple(findings),
        over_limit=max(0, len(raw) - MAX_FINDINGS),
        malformed=malformed,
        claims_cut=claims_cut,
    )


def _finding(entry: object) -> tuple[Finding, bool]:
    """One finding with exactly the D14 keys, or _Malformed."""
    if not isinstance(entry, Mapping) or set(entry) != _FINDING_KEYS:
        raise _Malformed("keys")
    line = entry["line"]
    if isinstance(line, bool) or not isinstance(line, int):
        raise _Malformed("line")
    if entry["severity"] not in SEVERITIES:
        raise _Malformed("severity")
    path, _ = _text(entry["path"], "path", 1024)
    claim, cut = _text(entry["claim"], "claim", MAX_CLAIM_CHARS)
    evidence, _ = _text(entry["evidence"], "evidence", MAX_EVIDENCE_CHARS)
    return Finding(path, line, entry["severity"], claim, evidence), cut


def _check(root: Path, path: str, start: int, end: int, symbol: str | None):
    citation = citations.Citation(path, start, end, symbol, 0)
    return citations.verify(root, [citation])[0]


def _drop_reason(root: Path, finding: Finding) -> str | None:
    """Why *finding* is dropped, or None when its path, line and evidence check out."""
    if finding.line < 1:
        return "no such line"
    where = _check(root, finding.path, finding.line, finding.line, None)
    if where.status == "not checked":
        return "a path outside the project or protected"
    if where.status != "verified":
        return "no such file" if "no such file" in where.reason else "no such line"
    evidence = finding.evidence.replace("\r\n", "\n").strip()
    if not evidence:
        return "no evidence"
    # The window around the line, clamped to the file: the verifier refuses an
    # end past the last line, so the end is walked down until it exists.
    start = max(1, finding.line - _NEAR)
    for end in range(finding.line + _NEAR, finding.line - 1, -1):
        near = _check(root, finding.path, start, end, evidence)
        if near.status == "verified":
            return None
        if "does not exist" not in near.reason:
            break
    return "evidence not at that line"


def validate(
    root: Path | str,
    review: ReviewFindings,
    changed: Mapping[str, set[int]],
) -> ValidatedReview:
    """Keep the findings that check out against the repository (D14, item 3).

    *changed* maps each path the step changed (forward slashes) to the line
    numbers it changed in the new file. A ``defect`` on any other line is kept
    as a ``note``: it is about code the step did not touch.
    """
    base = Path(root)
    result = ValidatedReview(claims_cut=review.claims_cut)
    if review.over_limit:
        result.dropped["over the limit of 20"] += review.over_limit
    if review.malformed:
        result.dropped["not a finding (no path and line, or other keys)"] += (
            review.malformed
        )
    for finding in review.findings:
        reason = _drop_reason(base, finding)
        if reason is not None:
            result.dropped[reason] += 1
            continue
        key = finding.path.replace("\\", "/")
        severity = finding.severity
        if severity == "defect" and finding.line not in changed.get(key, set()):
            severity = "note"
            result.downgraded += 1
        result.kept.append(
            Finding(
                path=safe_text(key),
                line=finding.line,
                severity=severity,
                claim=safe_text(finding.claim),
                evidence=safe_text(finding.evidence),
            )
        )
    return result


def describe(result: ValidatedReview) -> dict[str, Any]:
    """Counts for the turn summary and the event (B-061c reads this)."""
    return {
        "shown": len(result.kept),
        "downgraded": result.downgraded,
        "dropped": dict(sorted(result.dropped.items())),
        "claims_cut": result.claims_cut,
    }
