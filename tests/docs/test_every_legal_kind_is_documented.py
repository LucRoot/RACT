"""Every kind in the closed ``EventKind`` vocabulary is documented in docs/EVENTS.md.

``tests/trace/test_every_emitted_kind_is_registered.py`` pins the code-to-Literal
direction: nothing may be emitted that is not registered. The round-2 audit
(seam 1, P2) found the other direction had drifted: eight kinds in
``LEGAL_EVENT_KINDS`` (``investigator.report``, ``plan.rewritten``,
``plan.risk_assessed``, ``reversal.suspicious``,
``sidecar.header.legacy_fallback``, ``trace.incremental_verify_resumed``,
``trace.torn_tail_detected``, ``trace.verify_completed``) had live producers
but no entry in the schema doc, so an auditor could not learn their payload
shapes from it. This test extracts the backticked dotted names from
docs/EVENTS.md the way the audit did and fails when a registered kind is
absent. Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import Path

from ract.trace.events import LEGAL_EVENT_KINDS

ROOT = Path(__file__).resolve().parents[2]
EVENTS_MD = ROOT / "docs" / "EVENTS.md"

# A backticked dotted name: lowercase segments joined by dots, matching how
# kinds appear in section headings and inline references. Dotted module paths
# are extracted too; the parity check is a subset test, so extra names do
# not matter, and names without a dot are ignored.
_BACKTICKED_DOTTED = re.compile(r"`([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)`")


def _documented_kinds() -> set[str]:
    """Backticked dotted names in docs/EVENTS.md (the audit's extraction)."""
    text = EVENTS_MD.read_text(encoding="utf-8")
    return set(_BACKTICKED_DOTTED.findall(text))


def test_extraction_finds_kinds_and_skips_undotted_names() -> None:
    documented = _documented_kinds()
    assert "run.started" in documented
    # Dotted module paths ride along in the same bucket; harmless for the
    # subset check below.
    assert "ract.trace.writer" in documented
    # A bare name has no dot and is not extracted.
    assert "ract" not in documented


def test_every_legal_kind_is_documented_in_events_md() -> None:
    missing = sorted(LEGAL_EVENT_KINDS - _documented_kinds())
    assert missing == [], (
        "kinds in LEGAL_EVENT_KINDS with no docs/EVENTS.md entry "
        f"(doc drift; add the kind's payload schema and bump the doc): {missing}"
    )
