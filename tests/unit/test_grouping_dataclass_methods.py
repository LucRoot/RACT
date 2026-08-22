"""v0.5.1 spec-completeness module_04 -- dataclass + methods rule.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md``
§Cross-Function Grouping bullet 1.

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH) — cross-function grouping absent.

Under test: :func:`ract.memory.grouping.group_symbols` fires the
``dataclass_methods`` rule for a Python ``@dataclass`` class and
returns every method defined in its body as a companion.
"""

from __future__ import annotations

from ract.memory.grouping import (
    RULE_DATACLASS_METHODS,
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


def test_dataclass_methods_rule_fires_and_gathers_methods_in_body():
    with SymbolIndex() as sym:
        # Class starts at line 5, ends at line 30.
        class_id = sym.insert_or_update(
            _row(
                name="User",
                kind="class",
                file_path="/repo/models.py",
                start_line=5,
                end_line=30,
                signature="@dataclass\nclass User:",
                content_hash="c1",
            )
        )
        # Methods inside the class body (line 8, 15, 22).
        m1 = sym.insert_or_update(
            _row(
                name="__init__",
                kind="method",
                file_path="/repo/models.py",
                start_line=8,
                end_line=12,
                signature="def __init__(self):",
                content_hash="m1",
            )
        )
        m2 = sym.insert_or_update(
            _row(
                name="full_name",
                kind="method",
                file_path="/repo/models.py",
                start_line=15,
                end_line=17,
                signature="def full_name(self) -> str:",
                content_hash="m2",
            )
        )
        # Method OUTSIDE class body (unrelated free helper at line 42).
        sym.insert_or_update(
            _row(
                name="outside_helper",
                kind="method",
                file_path="/repo/models.py",
                start_line=42,
                end_line=44,
                signature="def outside_helper(self):",
                content_hash="mout",
            )
        )
        primary = sym.find_by_name("User")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert len(groups) == 1
        group = groups[0]
        assert group.rule == RULE_DATACLASS_METHODS
        companion_names = sorted(c.name for c in group.companions)
        assert companion_names == ["__init__", "full_name"]
        assert m1 in {c.id for c in group.companions}
        assert m2 in {c.id for c in group.companions}


def test_dataclass_rule_off_produces_no_companions():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="User",
                kind="class",
                file_path="/repo/models.py",
                start_line=5,
                end_line=10,
                signature="@dataclass\nclass User:",
            )
        )
        sym.insert_or_update(
            _row(
                name="do_it",
                kind="method",
                file_path="/repo/models.py",
                start_line=7,
                end_line=8,
            )
        )
        primary = sym.find_by_name("User")[0]
        rules = GroupingRules(dataclass_methods=False)
        groups = group_symbols([primary], rules, index=sym)
        assert groups[0].rule == RULE_NONE
        assert groups[0].companions == ()


def test_non_dataclass_class_produces_no_companions():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Plain",
                kind="class",
                file_path="/repo/models.py",
                start_line=5,
                end_line=10,
                signature="class Plain:",  # no @dataclass
            )
        )
        sym.insert_or_update(
            _row(
                name="hello",
                kind="method",
                file_path="/repo/models.py",
                start_line=7,
                end_line=8,
            )
        )
        primary = sym.find_by_name("Plain")[0]
        groups = group_symbols([primary], GroupingRules(), index=sym)
        assert groups[0].rule == RULE_NONE
        assert groups[0].companions == ()


def test_dataclass_rule_deterministic_across_runs():
    with SymbolIndex() as sym:
        sym.insert_or_update(
            _row(
                name="Pair",
                kind="class",
                file_path="/repo/pair.py",
                start_line=1,
                end_line=20,
                signature="@dataclass(frozen=True)\nclass Pair:",
            )
        )
        for i, mname in enumerate(("m3", "m1", "m2"), start=2):
            sym.insert_or_update(
                _row(
                    name=mname,
                    kind="method",
                    file_path="/repo/pair.py",
                    start_line=i * 3,
                    end_line=i * 3 + 1,
                )
            )
        primary = sym.find_by_name("Pair")[0]
        g1 = group_symbols([primary], GroupingRules(), index=sym)
        g2 = group_symbols([primary], GroupingRules(), index=sym)
        n1 = [c.name for c in g1[0].companions]
        n2 = [c.name for c in g2[0].companions]
        assert n1 == n2  # order stable
        # Sorted by (file_path, start_line): m3 at line 6, m1 at line 9, m2 at line 12.
        assert n1 == ["m3", "m1", "m2"]
