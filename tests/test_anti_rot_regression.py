# Rooted by Dr. Lucas Root, Ph.D.
"""End-to-end anti-rot regression suite.

LR:: The anti-rot system exists to stop the exact rot RACT historically
suffered: copy a module, rename its identifiers, and ship a near-duplicate that
lexical detectors miss. These tests pin that three independent detectors
(DuplicationGuard, ConsolidationScanner, CompressionNoveltyDetector) all catch
the same renamed clone.
"""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

import pytest

from rootact.compression_novelty_detector import CompressionNoveltyDetector
from rootact.consolidate import ConsolidationScanner
from rootact.duplication_guard import DuplicationBlockedError, DuplicationGuard

STRICT_ENHANCED = """\
def strict_enhanced(value):
    if value is None:
        raise ValueError("value required")
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("value empty")
    return normalized
"""

STRICT_PLUS = """\
def strict_plus(input_text):
    if input_text is None:
        raise ValueError("value required")
    cleaned = input_text.strip().lower()
    if not cleaned:
        raise ValueError("value empty")
    return cleaned
"""

ROOTED_ORIGINAL = """\
def rooted_logic(value, context, result):
    bound = bind(value, context)
    verified = verify(bound, result)
    stamped = stamp(verified, context)
    payload = prepare(stamped)
    encoded = encode(payload)
    return ship(encoded)
"""

ROOTED_THREE_RENAME = """\
def alpha_thing(one, two, three):
    four = bind(one, two)
    five = verify(four, three)
    six = stamp(five, two)
    seven = prepare(six)
    eight = encode(seven)
    return ship(eight)
"""

FILLER_AUTH = """\
def authenticate(token, secret, audience):
    digest = hash_token(token, secret)
    verified = verify_digest(digest)
    session = build_session(verified, audience)
    return finalize(session)
"""

FILLER_CACHE = """\
def lookup(key, store, fallback):
    entry = store.get(key)
    hydrated = hydrate(entry)
    validated = validate(hydrated)
    return fallback(validated)
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "enhanced.py").write_text(STRICT_ENHANCED, encoding="utf-8")
    (tmp_path / "rooted.py").write_text(ROOTED_ORIGINAL, encoding="utf-8")
    (tmp_path / "auth.py").write_text(FILLER_AUTH, encoding="utf-8")
    (tmp_path / "cache.py").write_text(FILLER_CACHE, encoding="utf-8")
    return tmp_path


def test_duplication_guard_blocks_verbatim_clone(project: Path) -> None:
    guard = DuplicationGuard(project, threshold=0.85)
    with pytest.raises(DuplicationBlockedError):
        guard.check_and_block("enhanced_copy.py", STRICT_ENHANCED)


def test_duplication_guard_blocks_renamed_clone(project: Path) -> None:
    guard = DuplicationGuard(project, threshold=0.85)
    with pytest.raises(DuplicationBlockedError):
        guard.check_and_block("rooted_clone.py", ROOTED_THREE_RENAME)


def test_consolidate_scan_covers_renamed_pair(project: Path) -> None:
    (project / "rooted_clone.py").write_text(ROOTED_THREE_RENAME, encoding="utf-8")
    scanner = ConsolidationScanner(project)
    result = scanner.scan(similarity_threshold=0.50, merge_threshold=0.50)
    rooted_pairs = [
        proposal
        for proposal in result.proposals
        if "rooted.py" in {proposal.target, *proposal.sources}
        and "rooted_clone.py" in {proposal.target, *proposal.sources}
    ]
    assert rooted_pairs, (
        "expected a merge proposal covering rooted.py and rooted_clone.py"
    )


def test_novelty_detector_marks_renamed_clone_low(project: Path) -> None:
    detector = CompressionNoveltyDetector(project)
    score = detector.assess_new_artifact("rooted_clone.py", ROOTED_THREE_RENAME)
    assert score is not None
    assert score.verdict == "low"
    assert score.nearest is not None
    assert "rooted.py" in score.nearest
