# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Multi-file symbol renamer for RACT.

Performs safe, AST-guided rename of a module-level function or class across the
project. v0.1 renames the definition, same-module bare references, and
``from module import name`` imports in other modules.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

from rootact.symbol_graph import SymbolGraph


@dataclass
class RenameEdit:
    """A single text replacement in a source file."""

    path: Path
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    new_text: str


@dataclass
class RenameResult:
    """Result of a rename operation."""

    edits: list[RenameEdit]
    files_changed: list[str]
    symbol_id: str | None = None
    error: str | None = None


class SymbolRenamer:
    """Rename a module-level function or class across Python source files.

    LR:: This is the first building block of the multi-file refactor use case.
    It is intentionally conservative: it only touches module-level definitions,
    same-module bare references, and explicit ``from module import name``
    imports. It does not rename attribute access (module.name) or local
    variables in other modules.
    """

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = Path(project_dir)

    def rename(
        self, old_name: str, new_name: str, module: str | None = None
    ) -> RenameResult:
        """Rename *old_name* to *new_name*.

        If *module* is provided, only rename the symbol in that module.
        Otherwise rename all module-level symbols named *old_name*.
        """
        if not old_name or not new_name:
            return RenameResult(
                edits=[], files_changed=[], error="old_name and new_name are required"
            )
        if old_name == new_name:
            return RenameResult(edits=[], files_changed=[], error="names are identical")

        graph = SymbolGraph(self.project_dir).build()
        candidates = self._find_candidates(graph, old_name, module)
        if not candidates:
            return RenameResult(
                edits=[],
                files_changed=[],
                error=f"No module-level symbol named '{old_name}' found",
            )

        all_edits: list[RenameEdit] = []
        files_changed: set[str] = set()
        symbol_id: str | None = None

        for symbol_id in candidates:
            edits = self._rename_symbol(graph, symbol_id, new_name)
            all_edits.extend(edits)
            for edit in edits:
                rel = str(edit.path.relative_to(self.project_dir))
                files_changed.add(rel)

        return RenameResult(
            edits=all_edits,
            files_changed=sorted(files_changed),
            symbol_id=symbol_id,
        )

    def apply(self, result: RenameResult) -> None:
        """Apply all edits in *result* to disk."""
        edits_by_file: dict[Path, list[RenameEdit]] = {}
        for edit in result.edits:
            edits_by_file.setdefault(edit.path, []).append(edit)

        for path, edits in edits_by_file.items():
            text = path.read_text(encoding="utf-8")
            # Sort edits by position descending so earlier edits do not invalidate
            # later edit coordinates.
            sorted_edits = sorted(
                edits,
                key=lambda e: (e.end_line, e.end_col, e.start_line, e.start_col),
                reverse=True,
            )
            for edit in sorted_edits:
                text = self._apply_edit(text, edit)
            path.write_text(text, encoding="utf-8")

    def _find_candidates(
        self, graph: SymbolGraph, old_name: str, module: str | None
    ) -> list[str]:
        """Return symbol ids matching old_name and optional module scope."""
        candidates: list[str] = []
        for sym_id, node in graph.nodes.items():
            if node.symbol_type == "module":
                continue
            if node.name != old_name:
                continue
            if module is not None and node.module != module:
                continue
            candidates.append(sym_id)
        return candidates

    def _rename_symbol(
        self, graph: SymbolGraph, symbol_id: str, new_name: str
    ) -> list[RenameEdit]:
        """Return edits for renaming a single symbol."""
        node = graph.nodes.get(symbol_id)
        if node is None:
            return []

        module = node.module
        source_path = self.project_dir / _module_to_path(module)
        if not source_path.is_file():
            return []

        edits: list[RenameEdit] = []

        # Rename the definition in the source module.
        def_edit = self._find_definition_edit(source_path, node.name, new_name)
        if def_edit:
            edits.append(def_edit)

        # Rename same-module bare references.
        refs = (
            {symbol_id}
            | graph.nodes[symbol_id].incoming
            | graph.nodes[symbol_id].outgoing
        )
        for ref_id in refs:
            ref_node = graph.nodes.get(ref_id)
            if ref_node is None:
                continue
            if ref_node.module != module:
                continue
            edits.extend(
                self._find_name_edits(source_path, ref_node.name, node.name, new_name)
            )

        # Rename imports and imported references in other modules.
        for path in self._python_files():
            if path == source_path:
                continue
            edits.extend(self._find_import_edits(path, module, node.name, new_name))

        # Deduplicate overlapping edits (definition may also appear as a bare name).
        return self._dedupe_edits(edits)

    def _find_definition_edit(
        self, path: Path, old_name: str, new_name: str
    ) -> RenameEdit | None:
        """Return the edit for the definition node in *path*."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return None

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name == old_name:
                    return self._node_name_edit(path, node, new_name)
        return None

    def _find_name_edits(
        self, path: Path, scope_name: str, old_name: str, new_name: str
    ) -> list[RenameEdit]:
        """Rename bare Name nodes with id == old_name inside *scope_name*."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return []

        edits: list[RenameEdit] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == old_name:
                edits.append(self._name_edit(path, node, new_name))
        return edits

    def _find_import_edits(
        self, path: Path, source_module: str, old_name: str, new_name: str
    ) -> list[RenameEdit]:
        """Rename ``from source_module import old_name`` imports and usages."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return []

        imported_as: dict[str, str | None] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                # Support both absolute and same-top-level relative guesses.
                if not (
                    module_name == source_module
                    or module_name.endswith("." + source_module.split(".")[-1])
                ):
                    continue
                for alias in node.names:
                    if alias.name == old_name:
                        imported_as[old_name] = alias.asname

        if not imported_as:
            return []

        local_name = imported_as[old_name]
        if local_name is None:
            local_name = old_name

        edits: list[RenameEdit] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module != source_module:
                    continue
                for alias in node.names:
                    if alias.name == old_name and alias.asname is None:
                        edits.append(self._alias_edit(path, alias, new_name))
            elif isinstance(node, ast.Name) and node.id == local_name:
                edits.append(self._name_edit(path, node, new_name))
        return edits

    def _node_name_edit(
        self,
        path: Path,
        node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
        new_name: str,
    ) -> RenameEdit | None:
        """Return an edit replacing the name of a FunctionDef/ClassDef."""
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        line_idx = node.lineno - 1
        if line_idx >= len(lines):
            return None
        line_text = lines[line_idx]
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        if isinstance(node, ast.ClassDef):
            prefix = "class "
        prefix_pos = line_text.find(prefix)
        if prefix_pos < 0:
            return None
        start_col = prefix_pos + len(prefix)
        end_col = start_col + len(node.name)
        return RenameEdit(
            path=path,
            start_line=node.lineno,
            start_col=start_col,
            end_line=node.lineno,
            end_col=end_col,
            new_text=new_name,
        )

    def _name_edit(self, path: Path, node: ast.Name, new_name: str) -> RenameEdit:
        end_lineno = getattr(node, "end_lineno", node.lineno) or node.lineno
        end_col_offset = (
            getattr(node, "end_col_offset", node.col_offset) or node.col_offset
        )
        return RenameEdit(
            path=path,
            start_line=node.lineno,
            start_col=node.col_offset,
            end_line=end_lineno,
            end_col=end_col_offset,
            new_text=new_name,
        )

    def _alias_edit(self, path: Path, alias: ast.alias, new_name: str) -> RenameEdit:
        end_lineno = getattr(alias, "end_lineno", alias.lineno) or alias.lineno
        end_col_offset = (
            getattr(alias, "end_col_offset", alias.col_offset) or alias.col_offset
        )
        return RenameEdit(
            path=path,
            start_line=alias.lineno,
            start_col=alias.col_offset,
            end_line=end_lineno,
            end_col=end_col_offset,
            new_text=new_name,
        )

    def _apply_edit(self, text: str, edit: RenameEdit) -> str:
        """Apply a single edit to *text* and return the modified text."""
        lines = text.splitlines(keepends=True)
        # Locate the byte/character range. We operate on characters.
        start_pos = self._position_to_offset(lines, edit.start_line, edit.start_col)
        end_pos = self._position_to_offset(lines, edit.end_line, edit.end_col)
        return text[:start_pos] + edit.new_text + text[end_pos:]

    def _position_to_offset(self, lines: list[str], line: int, col: int) -> int:
        """Return the character offset for (1-based line, 0-based col)."""
        offset = 0
        for i, line_text in enumerate(lines, start=1):
            if i == line:
                return offset + min(col, len(line_text.rstrip("\n\r")))
            offset += len(line_text)
        return offset

    def _dedupe_edits(self, edits: list[RenameEdit]) -> list[RenameEdit]:
        """Remove edits with identical ranges."""
        seen: set[tuple[str, int, int, int, int]] = set()
        result: list[RenameEdit] = []
        for edit in edits:
            key = (
                str(edit.path),
                edit.start_line,
                edit.start_col,
                edit.end_line,
                edit.end_col,
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(edit)
        return result

    def _python_files(self) -> list[Path]:
        """Return all Python files in the project directory."""
        return [
            p for p in self.project_dir.rglob("*.py") if "__pycache__" not in p.parts
        ]


def _module_to_path(module: str) -> Path:
    return Path(module.replace(".", "/") + ".py")


# RACT 0.1.1 - Trust and tooling
