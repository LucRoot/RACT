"""TypeScript tree-sitter parser for the symbol index.

Chunking rule (master spec section "Chunk discipline / AST chunking
rules"):

- module, class, function, method, arrow function assigned to const
  at module scope, interface, type.
- JSDoc stays attached (the preceding block comment).
- Nested arrow functions inside a class method DO NOT surface as
  top-level symbols (Second Pass Q2). Only ``const foo = (...) =>``
  at module scope (optionally wrapped in ``export``) is promoted.

Grammar pin: ``tree-sitter-typescript`` 0.23.x.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

import tree_sitter_typescript

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.languages import GrammarVersionMismatchError, _installed_version
from ract.memory.symbol_index import SymbolRow


LANGUAGE_LABEL: str = "typescript"
SUPPORTED_GRAMMAR_VERSION: str = "0.23.2"


def _check_grammar_version() -> None:
    installed = _installed_version("tree-sitter-typescript")
    if not installed.startswith("0.23."):
        raise GrammarVersionMismatchError(
            language=LANGUAGE_LABEL,
            expected=SUPPORTED_GRAMMAR_VERSION,
            observed=installed,
        )


_check_grammar_version()
_LANGUAGE = Language(tree_sitter_typescript.language_typescript())
_PARSER = Parser(_LANGUAGE)


def _text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _hash_bytes(source: bytes, node: Any) -> str:
    return hashlib.sha256(source[node.start_byte : node.end_byte]).hexdigest()


def _tokens_of(source: bytes, node: Any) -> int:
    return len(_text(source, node).split())


def _signature(source: bytes, node: Any) -> str:
    return _text(source, node).split("\n", 1)[0].rstrip()


def _preceding_jsdoc(source: bytes, node: Any) -> str | None:
    """Return the immediately-preceding JSDoc block comment, or None."""
    prev = node.prev_sibling
    while prev is not None and prev.type == "comment":
        text = _text(source, prev).strip()
        if text.startswith("/**"):
            return text.strip("/* \n\t")
        prev = prev.prev_sibling
    return None


def _row(
    *,
    name: str,
    kind: str,
    file_path: str,
    node: Any,
    source: bytes,
    docstring: str | None = None,
    visibility: str | None = None,
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
        visibility=visibility,
        parent_symbol_id=None,
        language=LANGUAGE_LABEL,
        content_hash=_hash_bytes(source, node),
        token_count=_tokens_of(source, node),
        updated_at=None,
    )


def _unwrap_export(node: Any) -> Any:
    """Return the inner declaration under an ``export_statement``.

    For ``export class Foo { ... }`` the ``export_statement`` has the
    class as one of its children (not always at a fixed index). This
    helper returns the first child that is a recognised declaration
    type.
    """
    for child in node.children:
        if child.type in _DECLARATION_KINDS:
            return child
    return node


_DECLARATION_KINDS: frozenset[str] = frozenset(
    {
        "class_declaration",
        "function_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "lexical_declaration",
        "abstract_class_declaration",
    }
)


def _method_rows(source: bytes, file_path: str, class_body: Any) -> list[SymbolRow]:
    out: list[SymbolRow] = []
    for child in class_body.children:
        if child.type != "method_definition":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is None:
            continue
        # accessibility_modifier is a sibling before name; scan.
        visibility: str | None = None
        for sub in child.children:
            if sub.type == "accessibility_modifier":
                visibility = _text(source, sub)
                break
        out.append(
            _row(
                name=_text(source, name_node),
                kind="method",
                file_path=file_path,
                node=child,
                source=source,
                visibility=visibility,
            )
        )
    return out


def _handle_lexical(source: bytes, file_path: str, node: Any) -> list[SymbolRow]:
    """A ``const foo = ...`` at module scope. Emit iff RHS is arrow_function.

    The tree-sitter-typescript grammar folds ``const`` and ``let`` into
    the same ``lexical_declaration`` node; the keyword itself is the
    first non-anonymous child (``const`` or ``let``). Only ``const``
    is spec-legal per master spec section ``Chunk discipline / AST
    chunking rules``. Second Pass Q2 (CONFIRMED): the prior
    implementation accepted every ``lexical_declaration`` and
    incorrectly surfaced ``let foo = () => {}`` as a top-level symbol.
    """
    keyword: str | None = None
    for child in node.children:
        if child.type in ("const", "let"):
            keyword = child.type
            break
    if keyword != "const":
        return []
    out: list[SymbolRow] = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        value_node = child.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if value_node.type != "arrow_function":
            continue
        out.append(
            _row(
                name=_text(source, name_node),
                kind="function",
                file_path=file_path,
                node=child,
                source=source,
            )
        )
    return out


def parse(source: bytes, path: Path) -> list[SymbolRow]:
    """Parse ``source`` and return the flat symbol list for ``path``.

    Emitted kinds: ``class``, ``function``, ``method``, ``interface``,
    ``type``.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            f"typescript.parse: source must be bytes-like; got {type(source).__name__}"
        )
    tree = _PARSER.parse(bytes(source))
    file_path = str(path)
    rows: list[SymbolRow] = []
    for child in tree.root_node.children:
        target = child
        if child.type == "export_statement":
            target = _unwrap_export(child)
        _consume_declaration(source, file_path, target, rows)
    return rows


def _consume_declaration(
    source: bytes, file_path: str, node: Any, rows: list[SymbolRow]
) -> None:
    if node.type == "class_declaration" or node.type == "abstract_class_declaration":
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="class",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_jsdoc(source, node),
            )
        )
        if body is not None:
            rows.extend(_method_rows(source, file_path, body))
    elif node.type == "function_declaration":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="function",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_jsdoc(source, node),
            )
        )
    elif node.type == "interface_declaration":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="interface",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_jsdoc(source, node),
            )
        )
    elif node.type == "type_alias_declaration":
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="type",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_jsdoc(source, node),
            )
        )
    elif node.type == "lexical_declaration":
        rows.extend(_handle_lexical(source, file_path, node))


__all__ = [
    "LANGUAGE_LABEL",
    "SUPPORTED_GRAMMAR_VERSION",
    "parse",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
