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


def test_resolve_name_uses_import_bindings(tmp_path):
    (tmp_path / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from core import util\ndef run():\n    util()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "core.util" in graph.nodes["main.run"].outgoing


def test_builtin_name_collision_stays_dead(tmp_path):
    """A builtin call must not resolve to an unrelated project symbol."""
    (tmp_path / "all.py").write_text(
        "def all(items):\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "def run():\n    return all([1, 2, 3])\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert not graph.nodes["all.all"].incoming
    assert "all.all" not in graph.nodes["main.run"].outgoing


def test_stdlib_name_collision_stays_dead(tmp_path):
    """A stdlib import must not resolve to an unrelated project symbol."""
    (tmp_path / "collections.py").write_text(
        "class Counter:\n    pass\n", encoding="utf-8"
    )
    (tmp_path / "main.py").write_text(
        "from collections import Counter\ndef run():\n    return Counter()\n",
        encoding="utf-8",
    )
    graph = SymbolGraph(tmp_path).build()
    assert not graph.nodes["collections.Counter"].incoming
    assert "collections.Counter" not in graph.nodes["main.run"].outgoing


def test_self_reference_does_not_create_inbound_edge(tmp_path):
    """Top-level self-references in a module do not count as inbound refs."""
    (tmp_path / "self_ref.py").write_text(
        "def helper():\n    pass\nhelper()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert not graph.nodes["self_ref.helper"].incoming
    assert "self_ref.helper" not in graph.nodes["self_ref:<module>"].outgoing


def test_genuine_use_marks_module_live(tmp_path):
    """A cross-module reference still creates an inbound edge."""
    (tmp_path / "used.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from used import helper\ndef run():\n    helper()\n", encoding="utf-8"
    )
    graph = SymbolGraph(tmp_path).build()
    assert "used.helper" in graph.nodes["main.run"].outgoing
    assert "main.run" in graph.nodes["used.helper"].incoming


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


def test_src_layout_cross_module_reference(tmp_path):
    """Imports in a src/pkg layout resolve across the package boundary."""
    src = tmp_path / "src" / "pkg"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "core.py").write_text("def util(): pass\n", encoding="utf-8")
    (src / "main.py").write_text(
        "from pkg.core import util\ndef run():\n    util()\n",
        encoding="utf-8",
    )
    graph = SymbolGraph(tmp_path).build()
    assert "pkg.core.util" in graph.nodes
    assert "pkg.main.run" in graph.nodes
    assert "pkg.core.util" in graph.nodes["pkg.main.run"].outgoing


def test_ract_repo_has_cross_module_edges(tmp_path):
    """The symbol graph must resolve real internal imports in RACT itself."""
    from pathlib import Path

    project_root = Path(__file__).parent.parent
    graph = SymbolGraph(project_root).build(include_tests=False)
    cross_module = 0
    for node in graph.nodes.values():
        for out_id in node.outgoing:
            dst = graph.nodes[out_id]
            if node.module != dst.module:
                cross_module += 1
    assert cross_module > 100, f"expected many cross-module edges, got {cross_module}"


# RACT 0.1.1 - Trust and tooling
