"""v0.5.1 spec-completeness module_04 -- companion budget cascade.

Task-spec requirement: companions consume from the same budget as
the primary. If a companion cannot fit at the caller's ``format``,
:func:`ract.memory.retrieve._extend_with_grouping` MUST downgrade
it to :class:`~ract.memory.chunk.ChunkFormat.SIGNATURE` before
dropping. If even SIGNATURE cannot fit, the companion is added to
:attr:`RetrievalBundle.dropped_companions`.

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH).
"""

from __future__ import annotations

from pathlib import Path

from ract.memory.chunk import ChunkFormat
from ract.memory.retrieve import (
    IndexKind,
    IndexRef,
    RetrievalQuery,
    retrieve,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _row(**kw) -> SymbolRow:
    defaults = dict(
        id=None,
        name="",
        kind="function",
        file_path="",
        start_line=None,
        end_line=None,
        signature="",
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    defaults.update(kw)
    return SymbolRow(**defaults)


def _seed_dataclass_with_fat_methods(tmp_path: Path) -> tuple[SymbolIndex, list]:
    """Seed a dataclass whose methods have LARGE bodies but SHORT
    signatures, so full-format cannot fit under a tight budget but
    SIGNATURE-format can.
    """
    fp = tmp_path / "big.py"
    header = "@dataclass\nclass Big:\n"
    fat_body = "        pass  # " + ("x " * 200) + "\n"
    body = (
        header
        + "    def m1(self) -> None:\n"
        + fat_body
        + "    def m2(self) -> None:\n"
        + fat_body
    )
    fp.write_text(body, encoding="utf-8")

    sym = SymbolIndex(str(tmp_path / "sym.db"))
    class_id = sym.insert_or_update(
        _row(
            name="Big",
            kind="class",
            file_path=str(fp),
            start_line=1,
            end_line=6,
            signature="@dataclass\nclass Big:",
            content_hash="c1",
            token_count=8,
        )
    )
    m1 = sym.insert_or_update(
        _row(
            name="m1",
            kind="method",
            file_path=str(fp),
            start_line=3,
            end_line=4,
            signature="def m1(self) -> None:",
            content_hash="m1",
            token_count=6,
        )
    )
    m2 = sym.insert_or_update(
        _row(
            name="m2",
            kind="method",
            file_path=str(fp),
            start_line=5,
            end_line=6,
            signature="def m2(self) -> None:",
            content_hash="m2",
            token_count=6,
        )
    )
    return sym, [class_id, m1, m2]


def test_companion_downgrades_to_signature_when_full_would_not_fit(
    tmp_path: Path,
):
    sym, _ = _seed_dataclass_with_fat_methods(tmp_path)
    try:
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        # Budget = enough for the primary's full body + companion
        # SIGNATURES only. The fat method bodies (>400 tokens each)
        # will not fit at FULL, but the short signatures do.
        query = RetrievalQuery(symbol_names=("Big",))
        bundle = retrieve(query, indexes, budget=200)
        primary_chunk = next(c for c in bundle.chunks if c.symbol_name == "Big")
        assert primary_chunk.body.strip() != ""
        # Companion chunks present but rendered as SIGNATURE (body
        # equals the signature text; no fat body).
        m1_chunk = next((c for c in bundle.chunks if c.symbol_name == "m1"), None)
        m2_chunk = next((c for c in bundle.chunks if c.symbol_name == "m2"), None)
        assert m1_chunk is not None
        assert m2_chunk is not None
        assert m1_chunk.body.startswith("def m1")
        # SIGNATURE format returns just the signature; no fat body.
        assert "pass" not in m1_chunk.body
        # Grouping event tagged the downgraded format.
        evts = [
            e for e in bundle.grouping_events if e["rule_fired"] == "dataclass_methods"
        ]
        assert evts, "dataclass_methods rule should have fired"
        assert evts[0]["companion_format"] == ChunkFormat.SIGNATURE.value
        assert evts[0]["companion_count"] == 2
        assert bundle.dropped_companions == ()
    finally:
        sym.close()


def test_companion_dropped_when_even_signature_would_not_fit(tmp_path: Path):
    sym, _ = _seed_dataclass_with_fat_methods(tmp_path)
    try:
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        # Ultra-tight budget: enough for the primary at Level 4
        # SIGNATURE only. Companions cannot fit at any format.
        # (The four-level cascade will drop to SIGNATURE for the
        # primary itself; companions get the same treatment.)
        query = RetrievalQuery(symbol_names=("Big",))
        bundle = retrieve(query, indexes, budget=10)
        # Primary present as SIGNATURE (fits in 10 tokens).
        assert any(c.symbol_name == "Big" for c in bundle.chunks)
        # Companions dropped.
        assert "m1" in bundle.dropped_companions or "m2" in bundle.dropped_companions
        evts = [
            e for e in bundle.grouping_events if e["rule_fired"] == "dataclass_methods"
        ]
        assert evts
        assert evts[0]["dropped_companion_count"] >= 1
    finally:
        sym.close()
