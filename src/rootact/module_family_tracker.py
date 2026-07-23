# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Module-family tracker for the RootAct self-recursing loop.

The tracker classifies each completed milestone into a semantic family and
detects when the loop has stayed in one family for too many consecutive
iterations. When tunneling is detected, the loop prompt is seeded with
alternative use cases from the project's catalog so the management model is
pushed toward a different domain.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rootact.loop_planner import Milestone


# Family keywords are matched against milestone descriptions and acceptance
# criteria in order. The first match wins.
_FAMILY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "test-fixtures",
        ["fixture", "edge_case", "edge case", "test generation", "test case"],
    ),
    (
        "cli-ui",
        ["cli", "ui", "toggle", "yolo", "auto", "reload", "session", "terminal"],
    ),
    ("project-templates", ["init", "scaffold", "project template"]),
    ("skills", ["skill", "builtin skill"]),
    ("documentation", ["doc", "documentation", "readme", "audit", "quickstart"]),
    ("git", ["git", "commit", "stage", "branch", "tag"]),
    ("providers", ["provider", "model", "router", "backend", "health check"]),
    ("integrations", ["mcp", "retrieval", "diff", "web search", "search"]),
    ("loop-core", ["oracle", "milestone", "progress", "planner"]),
    ("safety", ["safety", "guardrail", "error-mask", "forbidden"]),
    ("quality", ["lint", "format", "refactor", "quality scorecard"]),
    ("openapi", ["openapi", "swagger", "api client", "api server"]),
    ("memory", ["memory", "provenance", "history", "arena"]),
    ("rollback", ["rollback", "checkpoint", "snapshot"]),
]


@dataclass(frozen=True)
class TunnelingSignal:
    """A detected tunneling pattern."""

    family: str
    consecutive_count: int
    limit: int


def classify_milestone(milestone: Milestone) -> str:
    """Return the semantic family for a milestone.

    Multi-word keywords are matched as phrases; single-word keywords are matched
    as whole words to avoid substring false positives (e.g., 'ui' inside
    'built-in').
    """
    text = f"{milestone.description} {milestone.acceptance}".lower()
    words = set(re.findall(r"\b[\w-]+\b", text))
    for family, keywords in _FAMILY_KEYWORDS:
        for keyword in keywords:
            if " " in keyword:
                if keyword in text:
                    return family
            elif keyword in words:
                return family
    return "general"


def detect_tunneling(families: list[str], limit: int = 3) -> TunnelingSignal | None:
    """Return a signal if the last *limit* completed families are identical."""
    if len(families) < limit or limit < 1:
        return None
    recent = families[-limit:]
    first = recent[0]
    if first == "general":
        return None
    if all(f == first for f in recent):
        return TunnelingSignal(family=first, consecutive_count=limit, limit=limit)
    return None


def _load_accepted_use_cases(project_dir: Path) -> list[dict[str, Any]]:
    """Return accepted use cases from the project's JSONL catalog."""
    catalog = project_dir / "docs" / "internal" / "use_cases.jsonl"
    if not catalog.is_file():
        catalog = project_dir / "rootact_use_cases.jsonl"
    if not catalog.is_file():
        catalog = project_dir / "_BUILD" / "rootact_use_cases.jsonl"
    if not catalog.is_file():
        return []
    cases: list[dict[str, Any]] = []
    try:
        with catalog.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                case = json.loads(line)
                if case.get("status") == "accepted":
                    cases.append(case)
    except (OSError, json.JSONDecodeError):
        return []
    return cases


def _family_conflicts_with_use_case(family: str, use_case: dict[str, Any]) -> bool:
    """Return True if the use-case title/description overlaps the tunneled family."""
    text = f"{use_case.get('title', '')} {use_case.get('description', '')}".lower()
    family_keywords = {
        "test-fixtures": ["fixture", "edge case", "test generation", "test case"],
        "cli-ui": ["cli", "ide", "toggle", "session"],
        "skills": ["skill"],
        "documentation": ["documentation", "doc", "readme"],
        "git": ["git"],
        "providers": ["provider", "model"],
        "integrations": ["mcp", "retrieval", "diff"],
        "loop-core": ["oracle", "milestone", "loop"],
        "safety": ["safety", "guardrail"],
        "quality": ["lint", "format", "refactor"],
        "openapi": ["openapi"],
        "project-templates": ["template", "init"],
        "memory": ["memory", "provenance"],
        "rollback": ["rollback", "checkpoint"],
    }
    keywords = family_keywords.get(family, [family])
    return any(keyword in text for keyword in keywords)


def build_diversity_prompt(
    signal: TunnelingSignal,
    project_dir: Path | str,
    sample_count: int = 4,
) -> str:
    """Return a prompt block that pushes the model out of the tunneled family.

    The block includes accepted use cases from the project catalog that are not
    in the tunneled family, plus a direct instruction to propose work in a
    different domain.
    """
    project_dir = Path(project_dir)
    cases = _load_accepted_use_cases(project_dir)
    alternatives = [
        case
        for case in cases
        if not _family_conflicts_with_use_case(signal.family, case)
    ][:sample_count]

    lines: list[str] = [
        f"[DIVERSITY PROMPT] The loop has completed {signal.consecutive_count} "
        f"consecutive milestones in the '{signal.family}' family. Avoid further "
        "tunneling. Propose the next milestone in a different domain.",
        "",
        "Under-served use cases from the project catalog:",
    ]
    if alternatives:
        for case in alternatives:
            title = case.get("title", "Untitled")
            value = case.get("value", "")
            lines.append(f"- {title}: {value}")
    else:
        lines.append("- (no catalog entries available; pick any new domain)")

    return "\n".join(lines)


# RACT 0.1.1 - Trust and tooling
