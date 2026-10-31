"""S-023: a tracked document cites no commit hash that does not resolve.

A history rewrite (R-001) changes every hash, and v0.5.1's CHANGELOG broke
once that way (``test_changelog_v051_shas_resolve_in_git``). New text cites
commit subjects or tags instead. This test reads every tracked Markdown file
at the root and under ``docs/``, finds the tokens shaped like a commit hash
(7 to 12 hex characters, or 40, with a digit and a letter), and asks git for
each. One that does not resolve fails the test, unless it is in
``tests/fixtures/doc_hashes_before_s023.txt``: the citations that already did
not resolve when this test was written, whose commits are not in this
repository. That list only shrinks: an entry no longer cited fails too.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FROZEN = REPO / "tests" / "fixtures" / "doc_hashes_before_s023.txt"
_HASH = re.compile(
    r"(?<![0-9A-Za-z_/.\-])(?:[0-9a-f]{40}|[0-9a-f]{7,12})(?![0-9A-Za-z_])"
)
# Hex-shaped words that are not hashes.
_WORDS = frozenset({"ed25519"})


def _git(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def cited_hashes(root: Path, files: list[str]) -> dict[str, set[str]]:
    """Each hash-shaped token in *files* (paths relative to *root*), with the files citing it."""
    found: dict[str, set[str]] = {}
    for rel in files:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for match in _HASH.finditer(text):
            token = match.group(0)
            if token in _WORDS:
                continue
            if not re.search(r"[0-9]", token) or not re.search(r"[a-f]", token):
                continue
            found.setdefault(token, set()).add(rel)
    return found


def unresolved(tokens: list[str]) -> set[str]:
    """The tokens that name no commit in this repository."""
    if not tokens:
        return set()
    proc = _git(
        "cat-file", "--batch-check", stdin="".join(f"{t}^{{commit}}\n" for t in tokens)
    )
    out: set[str] = set()
    for token, line in zip(tokens, proc.stdout.splitlines()):
        if line.endswith(" missing") or " ambiguous" in line:
            out.add(token)
    return out


def _frozen() -> set[tuple[str, str]]:
    rows = set()
    for line in FROZEN.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            token, path = line.split(maxsplit=1)
            rows.add((token, path.strip()))
    return rows


def _tracked_markdown() -> list[str]:
    proc = _git("ls-files", "*.md")
    return [
        p for p in proc.stdout.splitlines() if "/" not in p or p.startswith("docs/")
    ]


@pytest.fixture(scope="module")
def citations() -> dict[str, set[str]]:
    # B-138: the tests that use this are marked needs_history; the check that
    # stood here read a copied tree (a .git git cannot open) as a full one.
    return cited_hashes(REPO, _tracked_markdown())


@pytest.mark.needs_history
def test_no_document_cites_a_hash_that_does_not_resolve(citations) -> None:
    missing = unresolved(sorted(citations))
    allowed = _frozen()
    new = sorted(
        f"{path}: {token}"
        for token in missing
        for path in citations[token]
        if (token, path) not in allowed
    )
    assert not new, (
        "these documents cite a commit hash that does not resolve; cite the commit "
        "subject or a tag instead:\n" + "\n".join(new)
    )


@pytest.mark.needs_history
def test_the_frozen_list_only_names_citations_that_still_exist(citations) -> None:
    stale = sorted(
        f"{token} {path}"
        for token, path in _frozen()
        if path not in citations.get(token, set())
    )
    assert not stale, (
        "remove these lines from tests/fixtures/doc_hashes_before_s023.txt "
        "(the citation is gone):\n" + "\n".join(stale)
    )


# --- the scanner on planted text ---------------------------------------------


def test_the_scanner_finds_hashes_and_leaves_words(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text(
        "fixed in `1a2b3c4`, full 0123456789abcdef0123456789abcdef01234567; "
        "signed with ed25519; the word deadbeef and the number 1234567; "
        "an id 3fa85f6417174562b3fc2c963f66afa6; a path src/1a2b3c4d.py\n",
        encoding="utf-8",
    )
    found = cited_hashes(tmp_path, ["a.md"])
    assert set(found) == {"1a2b3c4", "0123456789abcdef0123456789abcdef01234567"}


@pytest.mark.needs_repository
def test_a_hash_that_names_no_commit_is_unresolved() -> None:
    head = _git("rev-parse", "--short=7", "HEAD").stdout.strip()
    assert unresolved([head, "0000000aaaaaaa"]) == {"0000000aaaaaaa"}
