"""v0.5.1 spec-completeness module_04 -- Rust trait + impls rule.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md``
§Cross-Function Grouping bullet 2: "A trait/interface and its
implementations retrieve together **when the query is about the
trait**".

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH).
"""

from __future__ import annotations

from ract.memory.grouping import (
    RULE_NONE,
    RULE_TRAIT_IMPLS,
    GroupingRules,
    group_symbols,
)
from ract.memory.retrieve import RetrievalQuery
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
        language="rust",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )
    defaults.update(kw)
    return SymbolRow(**defaults)


def test_trait_impls_rule_fires_when_query_is_trait_focused():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path="/repo/lib.rs",
                start_line=1,
                end_line=5,
                signature="trait Formatter {",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Debug",
                kind="impl",
                file_path="/repo/impls.rs",
                start_line=1,
                end_line=10,
                signature="impl Formatter for Debug {",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Pretty",
                kind="impl",
                file_path="/repo/impls.rs",
                start_line=12,
                end_line=20,
                signature="impl Formatter for Pretty {",
            )
        )
        # Non-matching impl (different trait).
        sym.insert_or_update(
            _row(
                name="impl Other for Debug",
                kind="impl",
                file_path="/repo/other.rs",
                start_line=1,
                end_line=5,
            )
        )
        primary = sym.find_by_name("Formatter")[0]
        query = RetrievalQuery(symbol_names=("Formatter",))
        groups = group_symbols([primary], GroupingRules(), index=sym, query=query)
        assert groups[0].rule == RULE_TRAIT_IMPLS
        names = sorted(c.name for c in groups[0].companions)
        assert names == [
            "impl Formatter for Debug",
            "impl Formatter for Pretty",
        ]


def test_trait_impls_rule_skipped_when_query_is_impl_focused():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path="/repo/lib.rs",
                start_line=1,
                end_line=5,
                signature="trait Formatter {",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Debug",
                kind="impl",
                file_path="/repo/impls.rs",
                start_line=1,
                end_line=10,
            )
        )
        primary = sym.find_by_name("Formatter")[0]
        # Query does NOT name the trait — it names the impl target.
        query = RetrievalQuery(symbol_names=("Debug",))
        groups = group_symbols([primary], GroupingRules(), index=sym, query=query)
        # The rule does not fire; primary-only group.
        assert groups[0].rule == RULE_NONE
        assert groups[0].companions == ()


def test_trait_impls_rule_fires_when_query_is_none():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path="/repo/lib.rs",
                start_line=1,
                end_line=5,
                signature="trait Formatter {",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Debug",
                kind="impl",
                file_path="/repo/impls.rs",
                start_line=1,
                end_line=10,
            )
        )
        primary = sym.find_by_name("Formatter")[0]
        # Pure API path: no query supplied → treat as trait-focused.
        groups = group_symbols([primary], GroupingRules(), index=sym, query=None)
        assert groups[0].rule == RULE_TRAIT_IMPLS
        assert len(groups[0].companions) == 1


def test_trait_impls_rule_off_produces_no_companions():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path="/repo/lib.rs",
                start_line=1,
                end_line=5,
                signature="trait Formatter {",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Debug",
                kind="impl",
                file_path="/repo/impls.rs",
                start_line=1,
                end_line=10,
            )
        )
        primary = sym.find_by_name("Formatter")[0]
        rules = GroupingRules(trait_impls=False)
        query = RetrievalQuery(symbol_names=("Formatter",))
        groups = group_symbols([primary], rules, index=sym, query=query)
        assert groups[0].rule == RULE_NONE
        assert groups[0].companions == ()


def test_trait_impls_rule_excludes_language_when_filtered_out():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path="/repo/lib.rs",
                start_line=1,
                end_line=5,
                signature="trait Formatter {",
                language="rust",
            )
        )
        primary = sym.find_by_name("Formatter")[0]
        # Language allowlist excludes rust.
        rules = GroupingRules(languages=frozenset({"python", "typescript"}))
        query = RetrievalQuery(symbol_names=("Formatter",))
        groups = group_symbols([primary], rules, index=sym, query=query)
        assert groups[0].rule == RULE_NONE
