# Rooted by Dr. Lucas Root, Ph.D.
"""Regression tests for copy-and-rename duplication detection."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

import pytest

from ract.duplication_guard import DuplicationGuard

# Historical near-duplicate from the RACT repo: strict_plus vs strict_enhanced
# normalize to identical structure once identifiers are renamed.
STRICT_ENHANCED = '''\
def strict_enhanced(value):
    """Enhanced strict checker."""
    if value is None:
        raise ValueError("value required")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value empty")
    return normalized
'''

STRICT_PLUS = '''\
def strict_plus(input_text):
    """Plus strict checker."""
    if input_text is None:
        raise ValueError("value required")
    cleaned = input_text.strip().lower()
    if not cleaned:
        raise ValueError("value empty")
    return cleaned
'''

ROOTED_THREE_RENAME = """\
def rooted_three(assumption, context, output):
    bound = bind(assumption, context)
    verified = verify(bound, output)
    return ship(verified)
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "enhanced.py").write_text(STRICT_ENHANCED)
    return tmp_path


def test_strict_plus_matches_strict_enhanced(project: Path) -> None:
    guard = DuplicationGuard(project, threshold=0.85)
    matches = guard.check("plus.py", STRICT_PLUS)
    assert any(m.name == "strict_enhanced" for m in matches), matches


def test_three_identifier_rename_clone_matches(project: Path) -> None:
    original = (
        "def rooted_three(value, ctx, result):\n"
        "    linked = bind(value, ctx)\n"
        "    checked = verify(linked, result)\n"
        "    return ship(checked)\n"
    )
    (project / "rooted.py").write_text(original)
    guard = DuplicationGuard(project, threshold=0.85)
    matches = guard.check("rooted_clone.py", ROOTED_THREE_RENAME)
    assert matches, "expected renamed clone to be flagged"
    assert matches[0].similarity >= 0.85
