# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Lightweight symbol graph for RACT.

Builds an in-memory graph of Python symbols (functions, classes, modules) and
their references. The graph is the foundation for the Codebase Historian and
the semantic duplication guard. It uses only the standard library so RACT stays
portable.
"""

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SymbolNode:
    """A symbol in the project graph."""

    id: str
    name: str
    module: str
    symbol_type: str  # "function", "class", "method", "module"
    line: int = 0
    outgoing: set[str] = field(default_factory=set)
    incoming: set[str] = field(default_factory=set)


class SymbolGraph:
    """In-memory symbol graph built from Python source files.

        LR:: The graph answers "what exists?" and "what calls what?" for the
    codebase. The Historian layers commit context on top; the duplication guard
    uses it to compare new symbols against existing ones.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.nodes: dict[str, SymbolNode] = {}

    def build(self, include_tests: bool = True) -> "SymbolGraph":
        """Scan the project directory and build the symbol graph.

        Args:
            include_tests: If False, exclude ``tests/`` directories and files
                whose names start with ``test_`` from the graph. This is useful
                when measuring production-code reachability.
        """
        self.nodes = {}
        py_files = [
            p for p in self.project_dir.rglob("*.py") if "__pycache__" not in p.parts
        ]
        if not include_tests:
            py_files = [
                p
                for p in py_files
                if "tests" not in p.parts and not p.name.startswith("test_")
            ]

        # Pass 1: create nodes.
        for path in py_files:
            self._index_file(path)

        # Pass 2: create edges.
        for path in py_files:
            self._link_file(path)

        return self

    def _relative_module(self, path: Path) -> str:
        rel = path.relative_to(self.project_dir).with_suffix("")
        return ".".join(rel.parts)

    def _index_file(self, path: Path) -> None:
        module = self._relative_module(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return

        module_id = f"{module}:<module>"
        if module_id not in self.nodes:
            self.nodes[module_id] = SymbolNode(
                id=module_id,
                name="<module>",
                module=module,
                symbol_type="module",
                line=1,
            )

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sym_id = f"{module}.{node.name}"
                if sym_id not in self.nodes:
                    self.nodes[sym_id] = SymbolNode(
                        id=sym_id,
                        name=node.name,
                        module=module,
                        symbol_type="function",
                        line=node.lineno,
                    )
            elif isinstance(node, ast.ClassDef):
                sym_id = f"{module}.{node.name}"
                if sym_id not in self.nodes:
                    self.nodes[sym_id] = SymbolNode(
                        id=sym_id,
                        name=node.name,
                        module=module,
                        symbol_type="class",
                        line=node.lineno,
                    )

    def _link_file(self, path: Path) -> None:
        module = self._relative_module(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return

        module_id = f"{module}:<module>"

        def visit(node: ast.AST, scope: str) -> None:
            # Track scope changes for methods and nested functions.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = f"{module}.{node.name}"

            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                target = self._resolve_name(module, node.id)
                if target and target != scope:
                    self._add_edge(scope, target)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                name = _attr_leaf(node)
                if name:
                    target = self._resolve_name(module, name)
                    if target and target != scope:
                        self._add_edge(scope, target)

            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, module_id)

    def _resolve_name(self, module: str, name: str) -> str | None:
        """Return the most likely symbol id for *name* in *module*."""
        # Prefer same-module symbol.
        local = f"{module}.{name}"
        if local in self.nodes:
            return local
        # Fall back to any module-level symbol with the same name.
        for node in self.nodes.values():
            if node.name == name and node.symbol_type in {"function", "class"}:
                return node.id
        return None

    def _add_edge(self, source: str, target: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        self.nodes[source].outgoing.add(target)
        self.nodes[target].incoming.add(source)

    def neighbors(self, symbol_id: str) -> list[str]:
        """Return outgoing neighbors of *symbol_id*."""
        node = self.nodes.get(symbol_id)
        if node is None:
            return []
        return sorted(node.outgoing)

    def references(self, symbol_id: str) -> list[str]:
        """Return symbols that reference *symbol_id*."""
        node = self.nodes.get(symbol_id)
        if node is None:
            return []
        return sorted(node.incoming)

    def find(self, name: str) -> list[SymbolNode]:
        """Return all symbols matching *name*."""
        return [n for n in self.nodes.values() if n.name == name]

    def search(self, keyword: str) -> list[SymbolNode]:
        """Return symbols whose name or module contains *keyword*."""
        kw = keyword.lower()
        return [
            n
            for n in self.nodes.values()
            if kw in n.name.lower() or kw in n.module.lower()
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            nid: {
                "id": n.id,
                "name": n.name,
                "module": n.module,
                "symbol_type": n.symbol_type,
                "line": n.line,
                "outgoing": sorted(n.outgoing),
                "incoming": sorted(n.incoming),
            }
            for nid, n in self.nodes.items()
        }

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, project_dir: Path, path: Path | str) -> "SymbolGraph":
        """Load a previously saved graph without rebuilding."""
        graph = cls(project_dir)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for nid, n in data.items():
            graph.nodes[nid] = SymbolNode(
                id=n["id"],
                name=n["name"],
                module=n["module"],
                symbol_type=n["symbol_type"],
                line=n["line"],
                outgoing=set(n.get("outgoing", [])),
                incoming=set(n.get("incoming", [])),
            )
        return graph


def _attr_leaf(node: ast.Attribute) -> str | None:
    """Return the leaf attribute name of an attribute access chain."""
    if isinstance(node.value, ast.Name):
        return node.attr
    if isinstance(node.value, ast.Attribute):
        return _attr_leaf(node.value)
    return None


# RACT 0.1.0 - Initial Public Release
