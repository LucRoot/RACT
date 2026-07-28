"""Tests for the multi-file symbol renamer."""

from __future__ import annotations


import ast

from ract.symbol_graph import SymbolGraph
from ract.symbol_renamer import SymbolRenamer


def test_rename_function_in_same_module(tmp_path):
    (tmp_path / "mod.py").write_text(
        "def helper():\n    return 1\ndef caller():\n    return helper()\n",
        encoding="utf-8",
    )
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("helper", "assist")
    assert result.error is None
    renamer.apply(result)

    text = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "def assist():" in text
    assert "return assist()" in text
    assert "def helper():" not in text


def test_rename_class_in_same_module(tmp_path):
    (tmp_path / "mod.py").write_text(
        "class OldName:\n    pass\nobj = OldName()\n", encoding="utf-8"
    )
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("OldName", "NewName")
    assert result.error is None
    renamer.apply(result)

    text = (tmp_path / "mod.py").read_text(encoding="utf-8")
    assert "class NewName:" in text
    assert "obj = NewName()" in text


def test_rename_updates_imports_in_other_modules(tmp_path):
    (tmp_path / "core.py").write_text("def process():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "from core import process\nresult = process()\n", encoding="utf-8"
    )
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("process", "handle")
    assert result.error is None
    renamer.apply(result)

    core = (tmp_path / "core.py").read_text(encoding="utf-8")
    main = (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "def handle():" in core
    assert "from core import handle" in main
    assert "result = handle()" in main


def test_rename_with_module_scope(tmp_path):
    (tmp_path / "a.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("helper", "assist", module="a")
    assert result.error is None
    renamer.apply(result)

    a = (tmp_path / "a.py").read_text(encoding="utf-8")
    b = (tmp_path / "b.py").read_text(encoding="utf-8")
    assert "def assist():" in a
    assert "def helper():" in b


def test_rename_missing_symbol_returns_error(tmp_path):
    (tmp_path / "mod.py").write_text("def helper(): pass\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("missing", "found")
    assert result.error is not None
    assert "missing" in result.error


def test_rename_identical_names_returns_error(tmp_path):
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("same", "same")
    assert result.error is not None


def test_rename_preserves_local_variables_in_other_modules(tmp_path):
    (tmp_path / "core.py").write_text("def process():\n    pass\n", encoding="utf-8")
    (tmp_path / "main.py").write_text(
        "def run():\n    process = 1\n    return process\n", encoding="utf-8"
    )
    renamer = SymbolRenamer(tmp_path)
    result = renamer.rename("process", "handle", module="core")
    renamer.apply(result)

    main = (tmp_path / "main.py").read_text(encoding="utf-8")
    # Without an import, the local variable should not be renamed.
    assert "process = 1" in main
    assert "return process" in main


def test_rename_empty_name_returns_error(tmp_path):
    renamer = SymbolRenamer(tmp_path)
    assert renamer.rename("", "x").error is not None
    assert renamer.rename("x", "").error is not None


def test_rename_with_missing_source_file_returns_empty_edits(tmp_path):
    (tmp_path / "mod.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    graph = SymbolGraph(tmp_path).build()
    # Remove the source file after building the graph.
    (tmp_path / "mod.py").unlink()
    edits = renamer._rename_symbol(graph, "mod.helper", "assist")
    assert edits == []


def test_find_definition_edit_handles_syntax_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("def helper(\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    assert renamer._find_definition_edit(path, "helper", "assist") is None


def test_find_name_edits_handles_syntax_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("x = \n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    assert renamer._find_name_edits(path, "scope", "old", "new") == []


def test_find_definition_edit_returns_none_when_name_missing(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("def other(): pass\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    assert renamer._find_definition_edit(path, "helper", "assist") is None


def test_find_import_edits_ignores_mismatched_module(tmp_path):
    path = tmp_path / "main.py"
    path.write_text("from other import process\nresult = process()\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    edits = renamer._find_import_edits(path, "core", "process", "handle")
    assert edits == []


def test_find_import_edits_skips_importfrom_with_different_module(tmp_path):
    path = tmp_path / "main.py"
    path.write_text(
        "from core import process\nfrom other import process\nresult = process()\n",
        encoding="utf-8",
    )
    renamer = SymbolRenamer(tmp_path)
    edits = renamer._find_import_edits(path, "core", "process", "handle")
    # The matching import on line 1 is rewritten; the mismatched import on line 2 is not.
    assert any(e.start_line == 1 and e.new_text == "handle" for e in edits)
    assert not any(e.start_line == 2 for e in edits)


def test_find_import_edits_handles_syntax_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text("from core import \n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    assert renamer._find_import_edits(path, "core", "process", "handle") == []


def test_node_name_edit_returns_none_when_line_missing(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("def helper():\n    pass\n", encoding="utf-8")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    node.lineno = 100
    renamer = SymbolRenamer(tmp_path)
    assert renamer._node_name_edit(path, node, "assist") is None


def test_node_name_edit_returns_none_when_prefix_missing(tmp_path):
    path = tmp_path / "mod.py"
    path.write_text("# no prefix here\n", encoding="utf-8")
    tree = ast.parse("def helper(): pass")
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    node.lineno = 1
    renamer = SymbolRenamer(tmp_path)
    assert renamer._node_name_edit(path, node, "assist") is None


def test_position_to_offset_returns_end_when_line_beyond_range(tmp_path):
    renamer = SymbolRenamer(tmp_path)
    lines = ["line1\n", "line2\n"]
    assert renamer._position_to_offset(lines, 10, 0) == len("".join(lines))


def test_rename_symbol_returns_empty_for_missing_node(tmp_path):
    (tmp_path / "mod.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    graph = SymbolGraph(tmp_path).build()
    assert renamer._rename_symbol(graph, "mod.missing", "assist") == []


def test_rename_symbol_skips_missing_reference_node(tmp_path):
    (tmp_path / "mod.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    renamer = SymbolRenamer(tmp_path)
    graph = SymbolGraph(tmp_path).build()
    # Inject a stale reference id that no longer exists in the graph.
    graph.nodes["mod.helper"].incoming.add("mod.missing")
    edits = renamer._rename_symbol(graph, "mod.helper", "assist")
    assert any(e.new_text == "assist" for e in edits)


# RACT 0.1.1 - Trust and tooling
