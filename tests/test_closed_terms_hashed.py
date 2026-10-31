"""Closed-list terms stored only as hashes: no tracked file may name them (B-161).

The release-surface test lists its closed-IP terms in plain words. These
further terms must not appear in plain words in any tracked file, this one
included, so only the SHA-256 of each term's normalised form is stored: its
lowercase letter and digit runs joined by single spaces. A tracked file is
read the same way, and every run of as many words as a term has is hashed
and looked up. A term inside an identifier (``a_term_b``) is found because
``_`` and ``-`` split words.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# sha256 of the normalised term -> its number of words.
_HASHED_TERMS: dict[str, int] = {
    "752115f45427e30c230603d78fa1bf560bfea9cc378e954dfd1f571540ddc184": 1,
    "e8e787b89d41a0f047cbe881d1e67de22d01dbebbbb3b4b5d9a8480e81b349db": 2,
    "f59d0e790d91af1c840d63db56ac10628acc91d7f52e20e41658838593b244f0": 5,
}

# The two files the release-surface test exempts for its own reasons.
_EXEMPT = {"tests/test_release_surface.py", "assets/demo.cast"}

_WORD = re.compile(r"[a-z0-9]+")


def _digest(words: list[str]) -> str:
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def hashed_hits(text: str, hashed: dict[str, int]) -> set[str]:
    """The hashes in ``hashed`` whose term occurs in ``text``."""
    words = _WORD.findall(text.lower())
    found = set()
    for size in set(hashed.values()):
        for i in range(len(words) - size + 1):
            digest = _digest(words[i : i + size])
            if digest in hashed:
                found.add(digest)
    return found


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [_REPO_ROOT / f for f in out.splitlines() if f not in _EXEMPT]


def test_the_matcher_finds_a_term_by_its_hash_alone() -> None:
    term = {_digest(["harmless", "example"]): 2}
    assert hashed_hits("a line naming a Harmless-Example here", term) == set(term)
    assert hashed_hits("inside an_identifier_harmless_example_too", term) == set(term)
    assert hashed_hits("harmless and example apart", term) == set()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "waits for R-002a: the scrub branch removes these mentions; until the operator "
        "merges it, 8 tracked places still name three hashed terms (D-152)"
    ),
)
def test_no_tracked_file_names_a_hashed_closed_term() -> None:
    hits: dict[str, int] = {}
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable: the release-surface grep skips these too
        found = hashed_hits(text, _HASHED_TERMS)
        if found:
            hits[path.relative_to(_REPO_ROOT).as_posix()] = len(found)
    assert not hits, f"tracked files naming a hashed closed term: {sorted(hits)}"
