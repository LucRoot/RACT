# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the symbol graph builder."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.symbol_graph import SymbolGraph


def test_indexes_function_and_class(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper(): pass\nclass Thing: pass\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "mod.helper" in graph.nodes
    assert "mod.Thing" in graph.nodes
    assert graph.nodes["mod.helper"].symbol_type == "function"
    assert graph.nodes["mod.Thing"].symbol_type == "class"


def test_creates_module_node(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    graph = SymbolGraph(tmp_path).build()
    assert "mod:<module>" in graph.nodes


def test_links_function_calls(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper(): pass\ndef caller():\n    helper()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "mod.caller" in graph.nodes["mod.helper"].incoming
    assert "mod.helper" in graph.nodes["mod.caller"].outgoing


def test_cross_module_reference(tmp_path):
    (tmp_path / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from core import util\ndef run():\n    util()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "core.util" in graph.nodes["main.run"].outgoing


def test_find_by_name(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    graph = SymbolGraph(tmp_path).build()
    matches = graph.find("helper")
    assert len(matches) == 1
    assert matches[0].name == "helper"


def test_search_by_keyword(tmp_path):
    (tmp_path / "payment_gateway.py").write_text(
        "def charge(): pass\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    matches = graph.search("payment")
    assert any("payment_gateway" in m.module for m in matches)


def test_save_and_load(tmp_path):
    (tmp_path / "mod.py").write_text("def a(): pass\n", encoding="utf-8")
    graph = SymbolGraph(tmp_path).build()
    save_path = tmp_path / "graph.json"
    graph.save(save_path)

    loaded = SymbolGraph.load(tmp_path, save_path)
    assert "mod.a" in loaded.nodes
    assert loaded.nodes["mod.a"].symbol_type == "function"


def test_empty_project(tmp_path):
    graph = SymbolGraph(tmp_path).build()
    assert graph.nodes == {}


def test_syntax_error_file_is_skipped(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(\n", encoding="utf-8")
    (tmp_path / "good.py").write_text("def ok(): pass\n", encoding="utf-8")
    graph = SymbolGraph(tmp_path).build()
    assert "good.ok" in graph.nodes
    assert "bad.broken" not in graph.nodes


def test_attribute_access_creates_edge(tmp_path):
    (tmp_path / "mod.py").write_text(
        "class Helper:\n    def run(self): pass\n"
        "def use():\n    h = Helper()\n    h.run()\n",
        encoding="utf-8",
    )
    graph = SymbolGraph(tmp_path).build()
    # The method is indexed at module scope as mod.run.
    assert "mod.run" in graph.nodes["mod.use"].outgoing


def test_neighbors_and_references(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper(): pass\ndef caller():\n    helper()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert graph.neighbors("mod.caller") == ["mod.helper"]
    assert graph.references("mod.helper") == ["mod.caller"]


def test_attribute_chain_resolves_inner_symbol(tmp_path):
    (tmp_path / "mod.py").write_text(
        "class Outer:\n    class Inner:\n        def work(self): pass\n"
        "def use():\n    Outer.Inner\n",
        encoding="utf-8",
    )
    graph = SymbolGraph(tmp_path).build()
    # The attribute chain Outer.Inner resolves to the Inner class.
    assert "mod.Inner" in graph.nodes["mod.use"].outgoing


def test_attr_leaf_recurses_on_attribute_chain() -> None:
    import ast

    from rootact.symbol_graph import _attr_leaf

    tree = ast.parse("a.b.c\n")
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    attr = stmt.value
    assert isinstance(attr, ast.Attribute)
    assert _attr_leaf(attr) == "b"


def test_attr_leaf_returns_none_for_call_base() -> None:
    import ast

    from rootact.symbol_graph import _attr_leaf

    tree = ast.parse("foo().bar\n")
    stmt = tree.body[0]
    assert isinstance(stmt, ast.Expr)
    attr = stmt.value
    assert isinstance(attr, ast.Attribute)
    assert _attr_leaf(attr) is None


def test_resolve_name_falls_back_to_any_module(tmp_path):
    (tmp_path / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from core import util\ndef run():\n    util()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "core.util" in graph.nodes["main.run"].outgoing


def test_add_edge_ignores_missing_nodes(tmp_path):
    graph = SymbolGraph(tmp_path).build()
    # Should not raise even though nodes do not exist.
    graph._add_edge("missing.a", "missing.b")


def test_neighbors_returns_empty_for_unknown_symbol(tmp_path):
    graph = SymbolGraph(tmp_path).build()
    assert graph.neighbors("not.real") == []


def test_references_returns_empty_for_unknown_symbol(tmp_path):
    graph = SymbolGraph(tmp_path).build()
    assert graph.references("not.real") == []
