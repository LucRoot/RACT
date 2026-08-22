"""v0.5.1 spec-completeness module_04 -- end-to-end grouping wire-in.

Verifies that :func:`ract.memory.retrieve.retrieve`, when called
against a seeded :class:`SymbolIndex`, returns a bundle whose
``chunks`` list includes both the query's primary AND the
companion symbols surfaced by the four grouping rules.

Audit finding: ``_BUILD/audit_2026-08-21c/lens_1C_retrieve_chunks.md``
C-1 (HIGH).
"""

from __future__ import annotations

from pathlib import Path

from ract.memory.events import NullEventSink
from ract.memory.grouping import (
    RULE_DATACLASS_METHODS,
    RULE_TEST_SUBJECT,
    RULE_TRAIT_IMPLS,
)
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


def test_retrieve_dataclass_pulls_methods_as_companions(tmp_path: Path):
    body = (
        "@dataclass\n"
        "class User:\n"
        "    id: int\n"
        "    name: str\n"
        "\n"
        "    def full_name(self) -> str:\n"
        "        return self.name\n"
        "\n"
        "    def to_dict(self) -> dict:\n"
        "        return {'id': self.id, 'name': self.name}\n"
    )
    fp = tmp_path / "models.py"
    fp.write_text(body, encoding="utf-8")
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    try:
        sym.insert_or_update(
            _row(
                name="User",
                kind="class",
                file_path=str(fp),
                start_line=1,
                end_line=10,
                signature="@dataclass\nclass User:",
                content_hash="c1",
                token_count=8,
            )
        )
        sym.insert_or_update(
            _row(
                name="full_name",
                kind="method",
                file_path=str(fp),
                start_line=6,
                end_line=7,
                signature="def full_name(self) -> str:",
                content_hash="m1",
                token_count=4,
            )
        )
        sym.insert_or_update(
            _row(
                name="to_dict",
                kind="method",
                file_path=str(fp),
                start_line=9,
                end_line=10,
                signature="def to_dict(self) -> dict:",
                content_hash="m2",
                token_count=4,
            )
        )
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        sink = NullEventSink()
        query = RetrievalQuery(symbol_names=("User",))
        bundle = retrieve(query, indexes, budget=10_000, sink=sink)
        surfaced = sorted(chunk.symbol_name for chunk in bundle.chunks)
        assert "User" in surfaced
        assert "full_name" in surfaced
        assert "to_dict" in surfaced
        # Grouping event emitted.
        kinds = [kind for kind, _ in sink.records]
        assert "retrieval.grouping.applied" in kinds
        # Grouping event captured on the bundle.
        rules = {evt["rule_fired"] for evt in bundle.grouping_events}
        assert RULE_DATACLASS_METHODS in rules
        assert bundle.dropped_companions == ()
    finally:
        sym.close()


def test_grouping_opt_out_flag_suppresses_companions(tmp_path: Path):
    body = "@dataclass\nclass User:\n    def hello(self): pass\n"
    fp = tmp_path / "models.py"
    fp.write_text(body, encoding="utf-8")
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    try:
        sym.insert_or_update(
            _row(
                name="User",
                kind="class",
                file_path=str(fp),
                start_line=1,
                end_line=3,
                signature="@dataclass\nclass User:",
                content_hash="c1",
            )
        )
        sym.insert_or_update(
            _row(
                name="hello",
                kind="method",
                file_path=str(fp),
                start_line=3,
                end_line=3,
                signature="def hello(self): pass",
                content_hash="m1",
            )
        )
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        # Opt out.
        query = RetrievalQuery(
            symbol_names=("User",),
            grouping_enabled=False,
        )
        bundle = retrieve(query, indexes, budget=10_000)
        names = {chunk.symbol_name for chunk in bundle.chunks}
        assert names == {"User"}
        assert bundle.grouping_events == ()
        assert bundle.dropped_companions == ()
    finally:
        sym.close()


def test_retrieve_trait_pulls_impls_when_query_targets_trait(tmp_path: Path):
    body_lib = "trait Formatter {\n    fn go();\n}\n"
    body_impls = (
        "impl Formatter for Debug {\n    fn go() {}\n}\n"
        "impl Formatter for Pretty {\n    fn go() {}\n}\n"
    )
    fp_lib = tmp_path / "lib.rs"
    fp_lib.write_text(body_lib, encoding="utf-8")
    fp_impls = tmp_path / "impls.rs"
    fp_impls.write_text(body_impls, encoding="utf-8")
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    try:
        sym.insert_or_update(
            _row(
                name="Formatter",
                kind="trait",
                file_path=str(fp_lib),
                start_line=1,
                end_line=3,
                signature="trait Formatter {",
                content_hash="t1",
                language="rust",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Debug",
                kind="impl",
                file_path=str(fp_impls),
                start_line=1,
                end_line=3,
                signature="impl Formatter for Debug {",
                content_hash="i1",
                language="rust",
            )
        )
        sym.insert_or_update(
            _row(
                name="impl Formatter for Pretty",
                kind="impl",
                file_path=str(fp_impls),
                start_line=4,
                end_line=6,
                signature="impl Formatter for Pretty {",
                content_hash="i2",
                language="rust",
            )
        )
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        query = RetrievalQuery(symbol_names=("Formatter",))
        bundle = retrieve(query, indexes, budget=10_000)
        names = {chunk.symbol_name for chunk in bundle.chunks}
        assert "Formatter" in names
        assert "impl Formatter for Debug" in names
        assert "impl Formatter for Pretty" in names
        rules = {evt["rule_fired"] for evt in bundle.grouping_events}
        assert RULE_TRAIT_IMPLS in rules
    finally:
        sym.close()


def test_retrieve_test_function_pulls_subject(tmp_path: Path):
    fp_src = tmp_path / "urls.py"
    fp_src.write_text("def parse_url(t): return t\n", encoding="utf-8")
    fp_tests = tmp_path / "test_urls.py"
    fp_tests.write_text(
        "def test_parse_url():\n    assert parse_url('x') == 'x'\n",
        encoding="utf-8",
    )
    sym = SymbolIndex(str(tmp_path / "sym.db"))
    try:
        sym.insert_or_update(
            _row(
                name="parse_url",
                kind="function",
                file_path=str(fp_src),
                start_line=1,
                end_line=1,
                signature="def parse_url(t):",
                content_hash="s1",
            )
        )
        sym.insert_or_update(
            _row(
                name="test_parse_url",
                kind="function",
                file_path=str(fp_tests),
                start_line=1,
                end_line=2,
                signature="def test_parse_url():",
                content_hash="t1",
            )
        )
        indexes = [IndexRef(kind=IndexKind.SYMBOL, index=sym)]
        query = RetrievalQuery(symbol_names=("test_parse_url",))
        bundle = retrieve(query, indexes, budget=10_000)
        names = {chunk.symbol_name for chunk in bundle.chunks}
        assert "test_parse_url" in names
        assert "parse_url" in names
        rules = {evt["rule_fired"] for evt in bundle.grouping_events}
        assert RULE_TEST_SUBJECT in rules
    finally:
        sym.close()
