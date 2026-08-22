"""v0.5.1 spec-completeness module_04 -- test + subject rule.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md``
§Cross-Function Grouping bullet 3: "A test function retrieves with
its subject function".

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH).
"""

from __future__ import annotations

from ract.memory.grouping import (
    RULE_TEST_SUBJECT,
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


def test_test_function_prefix_finds_subject():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="parse_url",
                kind="function",
                file_path="/repo/src/urls.py",
                start_line=1,
                end_line=8,
                signature="def parse_url(text: str) -> Url:",
            )
        )
        sym.insert_or_update(
            _row(
                name="test_parse_url",
                kind="function",
                file_path="/repo/tests/test_urls.py",
                start_line=10,
                end_line=15,
                signature="def test_parse_url():",
            )
        )
        primary = sym.find_by_name("test_parse_url")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert groups[0].rule == RULE_TEST_SUBJECT
        names = [c.name for c in groups[0].companions]
        assert names == ["parse_url"]


def test_test_class_prefix_finds_class_subject():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Widget",
                kind="class",
                file_path="/repo/src/widget.py",
                start_line=1,
                end_line=20,
                signature="class Widget:",
            )
        )
        sym.insert_or_update(
            _row(
                name="TestWidget",
                kind="class",
                file_path="/repo/tests/test_widget.py",
                start_line=1,
                end_line=30,
                signature="class TestWidget:",
            )
        )
        primary = sym.find_by_name("TestWidget")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert groups[0].rule == RULE_TEST_SUBJECT
        names = [c.name for c in groups[0].companions]
        assert names == ["Widget"]


def test_subject_query_does_not_pull_tests():
    """Directionality: subject -> tests would balloon bundles for
    infrastructure symbols. The rule is one-way."""
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="parse_url",
                kind="function",
                file_path="/repo/src/urls.py",
                start_line=1,
                end_line=8,
            )
        )
        sym.insert_or_update(
            _row(
                name="test_parse_url",
                kind="function",
                file_path="/repo/tests/test_urls.py",
                start_line=10,
                end_line=15,
            )
        )
        primary = sym.find_by_name("parse_url")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        # parse_url does not start with test_ or Test — no rule fires.
        # (function_type_aliases may fire with 0 companions if the
        # signature happens to look up nothing; either way, no
        # test_parse_url in the companions.)
        for companion in groups[0].companions:
            assert companion.name != "test_parse_url"


def test_test_subject_rule_off_produces_no_companions():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="parse_url",
                kind="function",
                file_path="/repo/src/urls.py",
                start_line=1,
                end_line=8,
            )
        )
        sym.insert_or_update(
            _row(
                name="test_parse_url",
                kind="function",
                file_path="/repo/tests/test_urls.py",
                start_line=10,
                end_line=15,
            )
        )
        primary = sym.find_by_name("test_parse_url")[0]
        rules = GroupingRules(test_subject=False)
        groups = group_symbols([primary], rules, index=sym)
        # test_subject off - may fall through to
        # function_type_aliases; assert only that the subject-name
        # companion is not there.
        assert not any(c.name == "parse_url" for c in groups[0].companions)


def test_test_function_with_no_matching_subject_produces_empty_group():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="test_lonely",
                kind="function",
                file_path="/repo/tests/test_lonely.py",
                start_line=1,
                end_line=3,
            )
        )
        primary = sym.find_by_name("test_lonely")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        # Rule fires (test_ prefix detected) but no subject found.
        assert groups[0].rule == RULE_TEST_SUBJECT
        assert groups[0].companions == ()
