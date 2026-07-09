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
import os
import sys
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


@dataclass(frozen=True)
class _ImportBinding:
    """Mapping from a local name to its imported source.

    *target_module* is the fully-qualified module the name comes from.
    *target_name* is the symbol within that module for ``from ... import ...``
    bindings; ``None`` for bare ``import module`` bindings.
    *is_project* is True only when the imported module lives inside the project.
    """

    local_name: str
    target_module: str
    target_name: str | None = None
    is_project: bool = False


class SymbolGraph:
    """In-memory symbol graph built from Python source files.

        LR:: The graph answers "what exists?" and "what calls what?" for the
    codebase. The Historian layers commit context on top; the duplication guard
    uses it to compare new symbols against existing ones.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)
        self.nodes: dict[str, SymbolNode] = {}
        self._imports: dict[str, dict[str, _ImportBinding]] = {}
        self._project_modules: set[str] = set()
        # Detect the package root so module ids use the same namespace as imports.
        # e.g. project_dir "ract-work" with "src/rootact/__init__.py" ->
        # package_root "src/rootact", package_name "rootact".
        self._package_root, self._package_name = self._detect_package_root()

    def build(self, include_tests: bool = True) -> "SymbolGraph":
        """Scan the project directory and build the symbol graph.

        Args:
            include_tests: If False, exclude ``tests/`` directories and files
                whose names start with ``test_`` from the graph. This is useful
                when measuring production-code reachability.
        """
        self.nodes = {}
        self._imports = {}
        ignored_dirs = {
            "__pycache__",
            ".git",
            ".venv",
            ".venv-wsl-mutmut",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "node_modules",
            "_BUILD",
            "htmlcov",
            "dist",
            "build",
        }
        # Use os.walk so we can prune ignored directories before descending into
        # them. This avoids WSL filesystem junctions (e.g. .venv-wsl-mutmut/lib64)
        # that Windows pathlib cannot stat.
        py_files: list[Path] = []
        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            py_files.extend(Path(root) / f for f in files if f.endswith(".py"))
        if not include_tests:
            py_files = [
                p
                for p in py_files
                if "tests" not in p.parts and not p.name.startswith("test_")
            ]

        self._project_modules = {self._relative_module(p) for p in py_files}

        # Pass 1: create nodes and collect import bindings.
        for path in py_files:
            self._index_file(path)
            self._parse_imports(path)

        # Pass 2: create edges.
        for path in py_files:
            self._link_file(path)

        return self

    def _detect_package_root(self) -> tuple[Path | None, str | None]:
        """Return the package root directory and package name, if detectable.

        Handles three common layouts:
        - ``src/<pkg>/__init__.py`` with project_dir at the repo root.
        - ``src/<pkg>/__init__.py`` with project_dir already at ``src/<pkg>``.
        - Flat ``<pkg>/__init__.py`` at the repo root.

        If no package init is found, fall back to the project directory.
        """
        # Case 1: project_dir is the repo root and contains src/<pkg>/__init__.py.
        src = self.project_dir / "src"
        if src.is_dir():
            for child in sorted(src.iterdir()):
                if child.is_dir() and (child / "__init__.py").is_file():
                    return child, child.name

        # Case 2: project_dir is already inside src/<pkg> (or a flat <pkg>).
        if (self.project_dir / "__init__.py").is_file():
            return self.project_dir, self.project_dir.name

        # Case 3: flat layout at repo root.
        for child in sorted(self.project_dir.iterdir()):
            if (
                child.is_dir()
                and child.name != "src"
                and (child / "__init__.py").is_file()
            ):
                return child, child.name
        return None, None

    def module_id_for_path(self, path: Path) -> str:
        """Return the dotted module id used internally for *path*."""
        return self._relative_module(path)

    def _relative_module(self, path: Path) -> str:
        if self._package_root is not None:
            try:
                rel = path.relative_to(self._package_root).with_suffix("")
                return f"{self._package_name}.{'.'.join(rel.parts)}"
            except ValueError:
                pass
        rel = path.relative_to(self.project_dir).with_suffix("")
        return ".".join(rel.parts)

    def _index_file(self, path: Path) -> None:
        module = self._relative_module(path)
        tree = self._parse(path)
        if tree is None:
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

    def _parse_imports(self, path: Path) -> None:
        module = self._relative_module(path)
        tree = self._parse(path)
        if tree is None:
            return

        imports: dict[str, _ImportBinding] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        local_name = alias.asname
                        target_module = alias.name
                    else:
                        # ``import a.b.c`` binds the first component ``a``.
                        local_name = alias.name.split(".")[0]
                        target_module = local_name
                    imports[local_name] = _ImportBinding(
                        local_name=local_name,
                        target_module=target_module,
                        target_name=None,
                        is_project=self._is_project_import(target_module),
                    )
            elif isinstance(node, ast.ImportFrom):
                if any(alias.name == "*" for alias in node.names):
                    continue
                from_module = self._resolve_import_from(module, node)
                if from_module is None:
                    continue
                for alias in node.names:
                    local_name = alias.asname or alias.name
                    imports[local_name] = _ImportBinding(
                        local_name=local_name,
                        target_module=from_module,
                        target_name=alias.name,
                        is_project=self._is_project_import(from_module),
                    )

        self._imports[module] = imports

    def _resolve_import_from(self, module: str, node: ast.ImportFrom) -> str | None:
        """Return the fully-qualified module an ImportFrom refers to."""
        level = node.level or 0
        name = node.module
        if level == 0:
            return name

        parts = module.split(".")
        if level > len(parts):
            return None
        base = parts[:-level]
        if name:
            base = base + [name]
        if not base:
            return None
        return ".".join(base)

    def _is_project_import(self, target_module: str) -> bool:
        """Return True when *target_module* resolves to a project source file.

        Builtin and standard-library module names take precedence over project
        files that happen to collide with them, so ``collections.Counter`` never
        resolves to a project ``collections.py``. Both package-prefixed absolute
        imports (``rootact.providers.router``) and relative imports
        (``providers.router`` from inside ``rootact``) are accepted.
        """
        top = target_module.split(".")[0]
        if top in sys.stdlib_module_names or top in sys.builtin_module_names:
            return False
        if target_module in self._project_modules:
            return True
        if self._package_name is not None:
            candidate = f"{self._package_name}.{target_module}"
            if candidate in self._project_modules:
                return True
        return False

    def _resolve_imported_module(self, target_module: str) -> str:
        """Return the internal module id for an imported module name.

        If the import is already package-prefixed, use it directly. If it is a
        relative import, prepend the package name. Non-project imports pass
        through unchanged.
        """
        if target_module in self._project_modules:
            return target_module
        if self._package_name is not None:
            candidate = f"{self._package_name}.{target_module}"
            if candidate in self._project_modules:
                return candidate
        return target_module

    def _parse(self, path: Path) -> ast.AST | None:
        try:
            return ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return None

    def _link_file(self, path: Path) -> None:
        module = self._relative_module(path)
        tree = self._parse(path)
        if tree is None:
            return

        module_id = f"{module}:<module>"
        imports = self._imports.get(module, {})

        def visit(node: ast.AST, scope: str) -> None:
            # Track scope changes for methods and nested functions.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = f"{module}.{node.name}"

            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                target = self._resolve_name(module, node.id, imports)
                if target and target != scope:
                    self._add_edge(scope, target)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
                target = self._resolve_attribute(module, node, imports)
                if target and target != scope:
                    self._add_edge(scope, target)

            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, module_id)

    def _resolve_name(
        self, module: str, name: str, imports: dict[str, _ImportBinding]
    ) -> str | None:
        """Return the most likely symbol id for *name* in *module*."""
        # Prefer same-module symbol.
        local = f"{module}.{name}"
        if local in self.nodes:
            return local

        binding = imports.get(name)
        if binding is None:
            return None

        if not binding.is_project:
            return None

        target_module = self._resolve_imported_module(binding.target_module)
        if binding.target_name:
            return f"{target_module}.{binding.target_name}"
        module_id = f"{target_module}:<module>"
        if module_id in self.nodes:
            return module_id
        return None

    def _resolve_attribute(
        self,
        module: str,
        node: ast.Attribute,
        imports: dict[str, _ImportBinding],
    ) -> str | None:
        """Resolve an attribute access to a symbol id if possible."""
        parts: list[str] = []
        current: ast.AST = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.reverse()
        root_name = current.id
        attr_chain = parts

        # Case 1: the root name is imported. Follow it into the imported module.
        binding = imports.get(root_name)
        if binding is not None:
            if not binding.is_project:
                return None
            target_module = self._resolve_imported_module(binding.target_module)
            if binding.target_name:
                base = f"{target_module}.{binding.target_name}"
            else:
                base = target_module
            candidate = ".".join([base] + attr_chain)
            if candidate in self.nodes:
                return candidate
            return None

        # Case 2: the root name is a symbol defined in the current module.
        local_root = f"{module}.{root_name}"
        if local_root in self.nodes:
            candidate = ".".join([module, root_name] + attr_chain)
            if candidate in self.nodes:
                return candidate
            # Fall back to the leaf attribute in the current module. This keeps
            # method calls like ``h.run()`` resolving to ``module.run`` when
            # ``h`` is an untracked local variable.
            leaf = attr_chain[-1]
            local_leaf = f"{module}.{leaf}"
            if local_leaf in self.nodes:
                return local_leaf
            return None

        # Case 3: untracked root; fall back to the leaf attribute in module.
        leaf = attr_chain[-1]
        local_leaf = f"{module}.{leaf}"
        if local_leaf in self.nodes:
            return local_leaf
        return None

    def _add_edge(self, source: str, target: str) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        # Self-edges from a module node to its own top-level symbols do not
        # count as inbound references.
        if source.endswith(":<module>") and target.startswith(
            source[: -len(":<module>")] + "."
        ):
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


# RACT 0.1.1 - Trust and Tooling
