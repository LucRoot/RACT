# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Generate API documentation from Python source.

Scans a project directory, extracts module/class/function docstrings and
signatures, and writes Markdown files that stay in sync with the code. This is
the concrete engine behind RACT's Documentation Mode.
"""

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class DocSymbol:
    """A documented symbol extracted from source."""

    name: str
    kind: str  # "module", "function", "class", "method"
    module: str
    line: int
    signature: str | None = None
    docstring: str | None = None
    parent: str | None = None


class DocGenerator:
    """Build Markdown API docs from a Python project.

    LR:: The generator is intentionally simple: it reads docstrings and
    signatures from the AST and writes one Markdown file per module. It does
    not execute code, so it is safe to run on untrusted source trees.
    """

    def __init__(self, project_dir: Path, output_dir: Path | None = None) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.output_dir = (
            Path(output_dir).resolve()
            if output_dir
            else self.project_dir / "docs" / "api"
        )

    def generate(self) -> list[Path]:
        """Generate Markdown docs for all Python files under the project.

        Returns the list of files written.
        """
        written: list[Path] = []
        for py_path in self._python_files():
            symbols = list(self._extract_symbols(py_path))
            if not symbols:
                continue
            # Skip modules that have no docstring and no exported symbols.
            if (
                len(symbols) == 1
                and symbols[0].kind == "module"
                and not symbols[0].docstring
            ):
                continue
            md = self._render_module(symbols)
            out_path = self._output_path_for(py_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(md, encoding="utf-8")
            written.append(out_path)

        index = self._render_index(written)
        index_path = self.output_dir / "index.md"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(index, encoding="utf-8")
        if index_path not in written:
            written.append(index_path)

        return written

    def _python_files(self) -> list[Path]:
        """Return Python files under the project directory, excluding caches."""
        return [
            p for p in self.project_dir.rglob("*.py") if "__pycache__" not in p.parts
        ]

    def _relative_module(self, path: Path) -> str:
        rel = path.relative_to(self.project_dir).with_suffix("")
        return ".".join(rel.parts)

    def _output_path_for(self, path: Path) -> Path:
        rel = path.relative_to(self.project_dir).with_suffix(".md")
        return self.output_dir / rel

    def _extract_symbols(self, path: Path) -> Iterator[DocSymbol]:
        module = self._relative_module(path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            return

        module_doc = ast.get_docstring(tree)
        yield DocSymbol(
            name="<module>",
            kind="module",
            module=module,
            line=1,
            docstring=module_doc,
        )

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield self._function_symbol(module, node)
            elif isinstance(node, ast.ClassDef):
                yield self._class_symbol(module, node)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield self._method_symbol(module, node, child)

    def _function_symbol(
        self, module: str, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> DocSymbol:
        return DocSymbol(
            name=node.name,
            kind="function",
            module=module,
            line=node.lineno,
            signature=self._format_signature(node),
            docstring=ast.get_docstring(node),
        )

    def _class_symbol(self, module: str, node: ast.ClassDef) -> DocSymbol:
        return DocSymbol(
            name=node.name,
            kind="class",
            module=module,
            line=node.lineno,
            docstring=ast.get_docstring(node),
        )

    def _method_symbol(
        self,
        module: str,
        class_node: ast.ClassDef,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> DocSymbol:
        return DocSymbol(
            name=node.name,
            kind="method",
            module=module,
            line=node.lineno,
            signature=self._format_signature(node),
            docstring=ast.get_docstring(node),
            parent=class_node.name,
        )

    def _format_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = ast.unparse(node.args)
        prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
        ret = ""
        if node.returns:
            ret = f" -> {ast.unparse(node.returns)}"
        return f"{prefix}{node.name}({args}){ret}"

    def _render_module(self, symbols: list[DocSymbol]) -> str:
        module = symbols[0].module
        module_sym = symbols[0]

        lines: list[str] = [
            f"# `{module}`",
            "",
        ]
        if module_sym.docstring:
            lines.append(module_sym.docstring)
            lines.append("")

        summary_symbols = [s for s in symbols if s.kind != "module"]
        if summary_symbols:
            lines.append("## Summary")
            lines.append("")
            lines.append("| Symbol | Kind | Line |")
            lines.append("|--------|------|------|")
            for sym in summary_symbols:
                anchor = self._anchor(sym)
                lines.append(f"| [{sym.name}](#{anchor}) | {sym.kind} | {sym.line} |")
            lines.append("")

        for sym in symbols:
            if sym.kind == "module":
                continue
            lines.extend(self._render_symbol(sym))

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("_Generated by RACT Documentation Mode._")
        lines.append("")
        return os.linesep.join(lines)

    def _render_symbol(self, sym: DocSymbol) -> list[str]:
        anchor = self._anchor(sym)
        prefix = (
            "async " if sym.signature and sym.signature.startswith("async ") else ""
        )
        sig = sym.signature or sym.name
        sig_display = sig.replace(prefix, "", 1) if prefix else sig
        header = f"### `{sig_display}` {{#{anchor}}}"
        lines = ["", header, ""]
        if sym.docstring:
            lines.append(sym.docstring)
            lines.append("")
        else:
            lines.append("_No docstring provided._")
            lines.append("")
        return lines

    def _anchor(self, sym: DocSymbol) -> str:
        if sym.parent:
            return f"{sym.parent.lower()}-{sym.name.lower()}"
        return sym.name.lower()

    def _render_index(self, written: list[Path]) -> str:
        lines = [
            "# API Documentation Index",
            "",
            "Modules documented by RACT:",
            "",
        ]
        for path in sorted(written):
            rel = path.relative_to(self.output_dir).as_posix()
            if rel == "index.md":
                continue
            name = rel.replace(".md", "").replace("/", ".")
            lines.append(f"- [`{name}`]({rel})")
        lines.append("")
        lines.append("_Generated by RACT Documentation Mode._")
        lines.append("")
        return os.linesep.join(lines)


# RACT 0.1.0 - Initial Public Release
