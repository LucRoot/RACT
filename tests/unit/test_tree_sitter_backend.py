"""Regression tests for :mod:`ract.parsers.tree_sitter_backend`."""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.parsers import tree_sitter_backend as tsb
from ract.parsers.tree_sitter_backend import (
    LANGUAGE_BY_EXTENSION,
    Language,
    ParseTree,
    language_for,
    parse,
    tree_sitter_available,
)


# ---------------------------------------------------------------------------
# language_for
# ---------------------------------------------------------------------------


def test_language_for_python_extensions() -> None:
    assert language_for("foo.py") is Language.PYTHON
    assert language_for("foo.pyi") is Language.PYTHON


def test_language_for_js_extensions() -> None:
    for ext in (".js", ".mjs", ".cjs", ".jsx"):
        assert language_for(f"foo{ext}") is Language.JAVASCRIPT


def test_language_for_ts_and_tsx_separate() -> None:
    assert language_for("foo.ts") is Language.TYPESCRIPT
    assert language_for("foo.tsx") is Language.TSX


def test_language_for_rust_and_go() -> None:
    assert language_for("lib.rs") is Language.RUST
    assert language_for("main.go") is Language.GO


def test_language_for_unknown_extension_returns_none() -> None:
    assert language_for("README.md") is None
    assert language_for("data.json") is None
    assert language_for("bin.exe") is None


def test_language_for_accepts_path_and_str() -> None:
    assert language_for(Path("a/b/foo.rs")) is Language.RUST
    assert language_for("a/b/foo.rs") is Language.RUST


def test_language_for_case_insensitive_suffix() -> None:
    assert language_for("FOO.PY") is Language.PYTHON


def test_extension_map_covers_mvp_languages() -> None:
    # Every MVP language must be reachable from at least one extension.
    reachable = set(LANGUAGE_BY_EXTENSION.values())
    for lang in Language:
        assert lang in reachable


# ---------------------------------------------------------------------------
# tree_sitter_available
# ---------------------------------------------------------------------------


def test_tree_sitter_available_true_when_installed() -> None:
    # tree-sitter is a hard runtime dep of RACT; always True here.
    assert tree_sitter_available() is True


# ---------------------------------------------------------------------------
# parse() -- happy path per language
# ---------------------------------------------------------------------------


def test_parse_python_clean() -> None:
    src = b"def foo(x):\n    return x + 1\n"
    tree = parse("m.py", src)
    assert tree is not None
    assert isinstance(tree, ParseTree)
    assert tree.language is Language.PYTHON
    assert tree.parse_errors == ()
    assert tree.source_bytes == src


def test_parse_javascript_clean() -> None:
    src = b"function foo(x) { return x + 1; }\n"
    tree = parse("m.js", src)
    assert tree is not None
    assert tree.language is Language.JAVASCRIPT
    assert tree.parse_errors == ()


def test_parse_typescript_clean() -> None:
    src = b"function foo(x: number): number { return x + 1; }\n"
    tree = parse("m.ts", src)
    assert tree is not None
    assert tree.language is Language.TYPESCRIPT
    assert tree.parse_errors == ()


def test_parse_tsx_clean() -> None:
    src = b"const A = () => <div>hi</div>;\n"
    tree = parse("m.tsx", src)
    assert tree is not None
    assert tree.language is Language.TSX


def test_parse_rust_clean() -> None:
    src = b"fn foo(x: i32) -> i32 { x + 1 }\n"
    tree = parse("m.rs", src)
    assert tree is not None
    assert tree.language is Language.RUST
    assert tree.parse_errors == ()


def test_parse_go_clean() -> None:
    src = b"package main\nfunc Foo(x int) int { return x + 1 }\n"
    tree = parse("m.go", src)
    assert tree is not None
    assert tree.language is Language.GO
    assert tree.parse_errors == ()


# ---------------------------------------------------------------------------
# parse() -- error path
# ---------------------------------------------------------------------------


def test_parse_python_syntax_error_reports_error_nodes() -> None:
    src = b"def foo(:\n"  # illegal
    tree = parse("m.py", src)
    assert tree is not None
    assert len(tree.parse_errors) >= 1


def test_parse_unsupported_extension_returns_none() -> None:
    assert parse("README.md", b"hello") is None


def test_parse_rejects_str_source() -> None:
    with pytest.raises(TypeError):
        parse("m.py", "def foo(): pass\n")  # type: ignore[arg-type]


def test_parse_accepts_bytearray_source() -> None:
    src = bytearray(b"def foo(): pass\n")
    tree = parse("m.py", src)
    assert tree is not None
    assert tree.language is Language.PYTHON


# ---------------------------------------------------------------------------
# Graceful degradation -- unavailable grammar
# ---------------------------------------------------------------------------


def test_parse_returns_none_when_grammar_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a missing grammar; parse should return None + WARN, not raise."""
    # Reset caches so our monkeypatch is exercised.
    tsb._reset_caches_for_tests()
    # Poison the JAVASCRIPT grammar loader by pre-marking it unavailable
    # (mirrors what an ImportError would do).
    tsb._GRAMMAR_UNAVAILABLE.add(Language.JAVASCRIPT)
    try:
        tree = parse("m.js", b"const x = 1;\n")
        assert tree is None
    finally:
        tsb._reset_caches_for_tests()


def test_parse_reload_after_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """After :func:`_reset_caches_for_tests` a subsequent parse works again."""
    tsb._reset_caches_for_tests()
    tsb._GRAMMAR_UNAVAILABLE.add(Language.PYTHON)
    assert parse("x.py", b"a=1\n") is None
    tsb._reset_caches_for_tests()
    tree = parse("x.py", b"a=1\n")
    assert tree is not None


# ---------------------------------------------------------------------------
# parse_file convenience
# ---------------------------------------------------------------------------


def test_parse_file_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "x.py"
    p.write_bytes(b"x = 1\n")
    tree = tsb.parse_file(p)
    assert tree is not None
    assert tree.language is Language.PYTHON


def test_parse_file_missing_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "nope.py"
    assert tsb.parse_file(p) is None


# ---------------------------------------------------------------------------
# iter_nodes / node_text
# ---------------------------------------------------------------------------


def test_iter_nodes_visits_all_descendants() -> None:
    src = b"def a():\n    return 1\n"
    tree = parse("m.py", src)
    assert tree is not None
    types = {getattr(n, "type", "") for n in tsb.iter_nodes(tree.root_node)}
    # module, function_definition, identifier, return_statement, integer, block, ...
    assert "function_definition" in types
    assert "identifier" in types


def test_iter_nodes_filter_by_type() -> None:
    src = b"def a():\n    def b():\n        return 1\n"
    tree = parse("m.py", src)
    assert tree is not None
    fns = list(tsb.iter_nodes(tree.root_node, node_types={"function_definition"}))
    assert len(fns) == 2


def test_node_text_slice_matches_source() -> None:
    src = b"x = 42\n"
    tree = parse("m.py", src)
    assert tree is not None
    for ident in tsb.iter_nodes(tree.root_node, node_types={"identifier"}):
        assert tsb.node_text(ident, src) == "x"
        break
