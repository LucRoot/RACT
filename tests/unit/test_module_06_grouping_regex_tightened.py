"""v0.5.2 hardening module_06 -- DA-B F-5.1 dataclass regex + honest docs.

Master spec: ``docs/RACT_v0.5.2_HARDENING_SPEC.md`` §5 module_06.
DA-B finding: ``_BUILD/audit_2026-08-22b/DA_B_runtime_trace_memory.md``
F-5.1 (LOW) -- dataclass grouping regex over-permissive; ``@my.dc``,
``@lib.dataclass``, ``@evil.attributes.dc`` all matched even though
the docstring claimed foreign aliases would NOT match.

Ox Alpha co-build Q7 verdict: KEEP the permissive regex, FIX the
docstring. Rationale: any project-local re-export of dataclass is a
LEGITIMATE dataclass; whitelisting forces enumerating every re-
export and converts unknown-but-legit aliases into silent misses.
The rare false-positive of ``@evil.dc`` degrades to slightly-broader
grouping -- retrieval noise, not correctness. This test pins the
current permissive behaviour so a future well-intentioned tightener
regresses it deliberately, not accidentally.
"""

from __future__ import annotations

from ract.memory.grouping import _DATACLASS_DECORATOR_RE, _looks_like_dataclass
from ract.memory.symbol_index import SymbolRow


def _sig(text: str) -> SymbolRow:
    return SymbolRow(
        id=None,
        name="Foo",
        kind="class",
        file_path="/repo/foo.py",
        start_line=1,
        end_line=2,
        signature=text,
        docstring=None,
        visibility=None,
        parent_symbol_id=None,
        language="python",
        content_hash=None,
        token_count=None,
        updated_at=None,
    )


class TestKnownShapesMatch:
    def test_bare_dataclass(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search("@dataclass\nclass Foo:")

    def test_dataclass_with_kwargs(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search(
            "@dataclass(frozen=True, slots=True)\nclass Foo:"
        )

    def test_dataclasses_dataclass(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search(
            "@dataclasses.dataclass\nclass Foo:"
        )

    def test_pydantic_dataclasses_dataclass(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search(
            "@pydantic.dataclasses.dataclass\nclass Foo:"
        )

    def test_attrs_dataclass(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search(
            "@attrs.dataclass\nclass Foo:"
        )

    def test_dc_alias(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search("@dc\nclass Foo:")


class TestPermissivePrefixIntentional:
    """v0.5.2 module_06 Ox Alpha Q7 verdict: project-local
    re-exports MATCH by design. The docstring now honestly says so.
    """

    def test_project_local_dataclass_reexport_matches(self) -> None:
        # A local re-export like ``from my_pkg.helpers import
        # dataclass``; the caller invokes as ``@my_pkg.dataclass``.
        # This is a LEGITIMATE dataclass and grouping SHOULD fire.
        assert _DATACLASS_DECORATOR_RE.search(
            "@my_pkg.dataclass\nclass Foo:"
        )

    def test_project_local_dc_reexport_matches(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search("@my.dc\nclass Foo:")

    def test_deep_chain_ending_in_dataclass_matches(self) -> None:
        assert _DATACLASS_DECORATOR_RE.search(
            "@a.b.c.dataclass\nclass Foo:"
        )


class TestArbitraryLocalAliasStillMisses:
    """Names not ending in .dataclass / .dc (bare or suffix) still
    fall outside the grouping -- the primary still surfaces from
    the query, caller can request methods explicitly.
    """

    def test_arbitrary_alias_no_dc_suffix_misses(self) -> None:
        assert not _DATACLASS_DECORATOR_RE.search(
            "@my_special_dataclass_helper\nclass Foo:"
        )

    def test_similar_but_not_matching_word_misses(self) -> None:
        # ``@dclass`` has no ``.dc`` or ``.dataclass`` boundary --
        # trailing \b anchors on the full identifier.
        assert not _DATACLASS_DECORATOR_RE.search(
            "@dclass\nclass Foo:"
        )


class TestLooksLikeDataclass:
    def test_python_class_with_dataclass_returns_true(self) -> None:
        assert _looks_like_dataclass(_sig("@dataclass\nclass Foo:"))

    def test_python_class_with_local_reexport_returns_true(self) -> None:
        # Intentional: local re-exports ARE dataclasses.
        assert _looks_like_dataclass(_sig("@my.dc\nclass Foo:"))

    def test_non_class_kind_returns_false(self) -> None:
        row = _sig("@dataclass\nclass Foo:")
        row = row._replace(kind="function")
        assert not _looks_like_dataclass(row)

    def test_non_python_language_returns_false(self) -> None:
        row = _sig("@dataclass\nclass Foo:")
        row = row._replace(language="rust")
        assert not _looks_like_dataclass(row)


class TestDocstringHonest:
    """Regression: v0.5.2 module_06 docstring must NOT re-introduce
    the false claim that project-local aliases fail to match.
    """

    def test_docstring_does_not_promise_local_alias_rejection(
        self,
    ) -> None:
        from ract.memory.grouping import _looks_like_dataclass

        doc = _looks_like_dataclass.__doc__ or ""
        # The doc must acknowledge that module-prefix chains DO
        # match; the historical false claim must be gone.
        assert (
            "DO match" in doc
            or "ANY module-prefix" in doc
            or "grouping DOES fire" in doc
        ), (
            "F-5.1 regression: the docstring should honestly "
            "acknowledge project-local re-export matches."
        )
