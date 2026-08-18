"""Go tree-sitter parser for the symbol index.

Chunking rule (master spec section "Chunk discipline / AST chunking
rules"):

- package, struct, interface, function, method.
- Preceding line comments stay attached (Go's doc-comment convention).

Grammar pin: ``tree-sitter-go`` 0.25.x.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

import tree_sitter_go

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.languages import GrammarVersionMismatchError, _installed_version
from ract.memory.symbol_index import SymbolRow


LANGUAGE_LABEL: str = "go"
SUPPORTED_GRAMMAR_VERSION: str = "0.25.0"


def _check_grammar_version() -> None:
    installed = _installed_version("tree-sitter-go")
    if not installed.startswith("0.25."):
        raise GrammarVersionMismatchError(
            language=LANGUAGE_LABEL,
            expected=SUPPORTED_GRAMMAR_VERSION,
            observed=installed,
        )


_check_grammar_version()
_LANGUAGE = Language(tree_sitter_go.language())
_PARSER = Parser(_LANGUAGE)


def _text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _hash_bytes(source: bytes, node: Any) -> str:
    return hashlib.sha256(source[node.start_byte : node.end_byte]).hexdigest()


def _tokens_of(source: bytes, node: Any) -> int:
    return len(_text(source, node).split())


def _signature(source: bytes, node: Any) -> str:
    return _text(source, node).split("\n", 1)[0].rstrip()


def _preceding_doc_comment(source: bytes, node: Any) -> str | None:
    """Collect a run of ``//`` comment lines immediately above."""
    lines: list[str] = []
    prev = node.prev_sibling
    while prev is not None and prev.type == "comment":
        text = _text(source, prev)
        if not text.startswith("//"):
            break
        lines.append(text.lstrip("/ ").strip())
        prev = prev.prev_sibling
    if not lines:
        return None
    return "\n".join(reversed(lines))


def _visibility_of(name: str) -> str:
    """Go's visibility rule: leading uppercase is exported."""
    if name and name[0].isupper():
        return "public"
    return "private"


def _row(
    *,
    name: str,
    kind: str,
    file_path: str,
    node: Any,
    source: bytes,
    docstring: str | None = None,
) -> SymbolRow:
    return SymbolRow(
        id=None,
        name=name,
        kind=kind,
        file_path=file_path,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        signature=_signature(source, node),
        docstring=docstring,
        visibility=_visibility_of(name),
        parent_symbol_id=None,
        language=LANGUAGE_LABEL,
        content_hash=_hash_bytes(source, node),
        token_count=_tokens_of(source, node),
        updated_at=None,
    )


def parse(source: bytes, path: Path) -> list[SymbolRow]:
    """Parse ``source`` and return the flat symbol list for ``path``.

    Emitted kinds: ``function``, ``method``, ``struct``, ``interface``.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            f"go.parse: source must be bytes-like; got {type(source).__name__}"
        )
    tree = _PARSER.parse(bytes(source))
    file_path = str(path)
    rows: list[SymbolRow] = []
    for child in tree.root_node.children:
        if child.type == "function_declaration":
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            rows.append(
                _row(
                    name=_text(source, name_node),
                    kind="function",
                    file_path=file_path,
                    node=child,
                    source=source,
                    docstring=_preceding_doc_comment(source, child),
                )
            )
        elif child.type == "method_declaration":
            name_node = child.child_by_field_name("name")
            if name_node is None:
                continue
            rows.append(
                _row(
                    name=_text(source, name_node),
                    kind="method",
                    file_path=file_path,
                    node=child,
                    source=source,
                    docstring=_preceding_doc_comment(source, child),
                )
            )
        elif child.type == "type_declaration":
            _consume_type_declaration(source, file_path, child, rows)

    return rows


def _consume_type_declaration(
    source: bytes, file_path: str, node: Any, rows: list[SymbolRow]
) -> None:
    doc = _preceding_doc_comment(source, node)
    for spec in node.children:
        if spec.type != "type_spec":
            continue
        name_node = spec.child_by_field_name("name")
        type_node = spec.child_by_field_name("type")
        if name_node is None or type_node is None:
            continue
        name = _text(source, name_node)
        if type_node.type == "struct_type":
            kind = "struct"
        elif type_node.type == "interface_type":
            kind = "interface"
        else:
            kind = "type"
        rows.append(
            _row(
                name=name,
                kind=kind,
                file_path=file_path,
                node=spec,
                source=source,
                docstring=doc,
            )
        )


__all__ = [
    "LANGUAGE_LABEL",
    "SUPPORTED_GRAMMAR_VERSION",
    "parse",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
