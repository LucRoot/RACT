"""v0.5.1 spec-completeness module_04 -- function + type aliases rule.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md``
§Cross-Function Grouping bullet 4: "A function retrieves with its
type aliases".

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH).
"""

from __future__ import annotations

from ract.memory.grouping import (
    RULE_FUNCTION_TYPE_ALIASES,
    RULE_NONE,
    GroupingRules,
    group_symbols,
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


def test_function_signature_finds_referenced_type_alias():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="UserId",
                kind="type",
                file_path="/repo/types.py",
                start_line=1,
                end_line=1,
                signature="UserId = int",
            )
        )
        sym.insert_or_update(
            _row(
                name="Response",
                kind="type",
                file_path="/repo/types.py",
                start_line=2,
                end_line=2,
                signature="Response = dict[str, str]",
            )
        )
        sym.insert_or_update(
            _row(
                name="handle",
                kind="function",
                file_path="/repo/api.py",
                start_line=5,
                end_line=10,
                signature="def handle(uid: UserId) -> Response:",
            )
        )
        primary = sym.find_by_name("handle")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert groups[0].rule == RULE_FUNCTION_TYPE_ALIASES
        names = sorted(c.name for c in groups[0].companions)
        assert names == ["Response", "UserId"]


def test_method_signature_type_aliases_also_resolve():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Payload",
                kind="type",
                file_path="/repo/types.py",
                start_line=1,
                end_line=1,
                signature="Payload = bytes",
            )
        )
        sym.insert_or_update(
            _row(
                name="send",
                kind="method",
                file_path="/repo/api.py",
                start_line=10,
                end_line=15,
                signature="def send(self, data: Payload) -> None:",
            )
        )
        primary = sym.find_by_name("send")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert groups[0].rule == RULE_FUNCTION_TYPE_ALIASES
        assert [c.name for c in groups[0].companions] == ["Payload"]


def test_function_with_no_type_alias_references_produces_empty_group():
    with SymbolIndex() as sym:
        # No type-kind row in the index.
        sym.insert_or_update(
            _row(
                name="Widget",
                kind="class",
                file_path="/repo/widget.py",
                start_line=1,
                end_line=5,
                signature="class Widget:",
            )
        )
        sym.insert_or_update(
            _row(
                name="handle",
                kind="function",
                file_path="/repo/api.py",
                start_line=5,
                end_line=10,
                signature="def handle(w: Widget) -> None:",
            )
        )
        primary = sym.find_by_name("handle")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        # Rule matched (function+python) but no type companions.
        assert groups[0].rule == RULE_FUNCTION_TYPE_ALIASES
        assert groups[0].companions == ()


def test_stopwords_do_not_leak_into_type_alias_lookup():
    """``def``, ``self``, ``None`` and ``list`` are stopwords in
    :data:`ract.memory.grouping._PY_SIG_STOPWORDS`; they must not
    fire spurious :meth:`SymbolIndex.find_by_name` hits.
    """
    with SymbolIndex() as sym:
        # Bogus row named "list" as a type - should NOT be picked up.
        sym.insert_or_update(
            _row(
                name="list",
                kind="type",
                file_path="/repo/types.py",
                start_line=1,
                end_line=1,
                signature="list = None  # sabotage",
            )
        )
        sym.insert_or_update(
            _row(
                name="run",
                kind="function",
                file_path="/repo/api.py",
                start_line=5,
                end_line=10,
                signature="def run(self, items: list) -> None:",
            )
        )
        primary = sym.find_by_name("run")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert all(c.name != "list" for c in groups[0].companions)


def test_function_type_aliases_rule_off_produces_no_companions():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="UserId",
                kind="type",
                file_path="/repo/types.py",
                start_line=1,
                end_line=1,
            )
        )
        sym.insert_or_update(
            _row(
                name="handle",
                kind="function",
                file_path="/repo/api.py",
                start_line=5,
                end_line=10,
                signature="def handle(uid: UserId) -> None:",
            )
        )
        primary = sym.find_by_name("handle")[0]
        rules = GroupingRules(function_type_aliases=False)
        groups = group_symbols([primary], rules, index=sym)
        assert groups[0].rule == RULE_NONE
        assert groups[0].companions == ()
