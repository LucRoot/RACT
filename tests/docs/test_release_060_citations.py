"""B-151: every test or document the 0.6.0 release-note drafts cite exists.

A citation is ``(cite: path)`` or ``(cite: path::test_name)``; the path must be a
file in the repository and the named test must be defined in it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DRAFTS = sorted((ROOT / "docs" / "release" / "0.6.0").glob("*.md"))
CITE = re.compile(r"\(cite: ([^)\s]+)\)")


def _citations() -> list[tuple[str, str]]:
    found = []
    for draft in DRAFTS:
        for ref in CITE.findall(draft.read_text(encoding="utf-8")):
            found.append((draft.name, ref))
    return found


def test_there_are_four_drafts_and_each_cites() -> None:
    names = {d.name for d in DRAFTS}
    assert names == {
        "CHANGELOG.md",
        "UPGRADING.md",
        "SECURITY_TIER3.md",
        "README_WHATS_NEW.md",
    }
    cited = {name for name, _ref in _citations()}
    assert cited == names


def test_each_draft_lists_what_it_does_not_claim() -> None:
    for draft in DRAFTS:
        assert "## Not claimed" in draft.read_text(encoding="utf-8"), draft.name


@pytest.mark.parametrize(("draft", "ref"), _citations())
def test_each_citation_exists(draft: str, ref: str) -> None:
    path, _, test = ref.partition("::")
    target = ROOT / path
    assert target.is_file(), f"{draft} cites {path}, which does not exist"
    if test:
        assert re.search(
            rf"^def {re.escape(test)}\(", target.read_text(encoding="utf-8"), re.M
        ), f"{draft} cites {ref}: no such test"
