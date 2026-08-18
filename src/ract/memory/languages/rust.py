"""Rust tree-sitter parser for the symbol index.

Chunking rule (master spec section "Chunk discipline / AST chunking
rules"):

- module, struct, enum, trait, impl block, function, method.
- Doc comments (``///`` lines) stay attached.

Grammar pin: ``tree-sitter-rust`` 0.24.x.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

import tree_sitter_rust

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.languages import GrammarVersionMismatchError, _installed_version
from ract.memory.symbol_index import SymbolRow


LANGUAGE_LABEL: str = "rust"
SUPPORTED_GRAMMAR_VERSION: str = "0.24.2"


def _check_grammar_version() -> None:
    installed = _installed_version("tree-sitter-rust")
    if not installed.startswith("0.24."):
        raise GrammarVersionMismatchError(
            language=LANGUAGE_LABEL,
            expected=SUPPORTED_GRAMMAR_VERSION,
            observed=installed,
        )


_check_grammar_version()
_LANGUAGE = Language(tree_sitter_rust.language())
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
    """Collect a run of ``///`` doc-comment lines immediately above."""
    lines: list[str] = []
    prev = node.prev_sibling
    while prev is not None:
        if prev.type != "line_comment":
            break
        text = _text(source, prev)
        if not text.startswith("///"):
            break
        lines.append(text.lstrip("/").strip())
        prev = prev.prev_sibling
    if not lines:
        return None
    return "\n".join(reversed(lines))


def _visibility_of(source: bytes, node: Any) -> str | None:
    for child in node.children:
        if child.type == "visibility_modifier":
            return _text(source, child)
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


def _name_of(node: Any) -> Any | None:
    named = node.child_by_field_name("name")
    if named is not None:
        return named
    for child in node.children:
        if child.type in ("type_identifier", "identifier"):
            return child
    return None


def _impl_name(source: bytes, node: Any) -> str:
    """Impl block name = ``impl <Trait> for <Type>`` or ``impl <Type>``.

    Rendered as a stable label from the AST fields tree-sitter-rust
    exposes.
    """
    type_node = node.child_by_field_name("type")
    trait_node = node.child_by_field_name("trait")
    type_label = _text(source, type_node) if type_node is not None else "<anon>"
    if trait_node is not None:
        return f"impl {_text(source, trait_node)} for {type_label}"
    return f"impl {type_label}"


def parse(source: bytes, path: Path) -> list[SymbolRow]:
    """Parse ``source`` and return the flat symbol list for ``path``.

    Emitted kinds: ``struct``, ``enum``, ``trait``, ``impl``,
    ``function``, ``method``.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            f"rust.parse: source must be bytes-like; got {type(source).__name__}"
        )
    tree = _PARSER.parse(bytes(source))
    file_path = str(path)
    rows: list[SymbolRow] = []
    for child in tree.root_node.children:
        _consume(source, file_path, child, rows)
    return rows


def _consume(source: bytes, file_path: str, node: Any, rows: list[SymbolRow]) -> None:
    if node.type == "struct_item":
        name_node = _name_of(node)
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="struct",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_doc_comment(source, node),
                visibility=_visibility_of(source, node),
            )
        )
    elif node.type == "enum_item":
        name_node = _name_of(node)
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="enum",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_doc_comment(source, node),
                visibility=_visibility_of(source, node),
            )
        )
    elif node.type == "trait_item":
        name_node = _name_of(node)
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="trait",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_doc_comment(source, node),
                visibility=_visibility_of(source, node),
            )
        )
    elif node.type == "impl_item":
        rows.append(
            _row(
                name=_impl_name(source, node),
                kind="impl",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_doc_comment(source, node),
            )
        )
        body = node.child_by_field_name("body")
        if body is not None:
            for sub in body.children:
                if sub.type == "function_item":
                    name_node = _name_of(sub)
                    if name_node is None:
                        continue
                    rows.append(
                        _row(
                            name=_text(source, name_node),
                            kind="method",
                            file_path=file_path,
                            node=sub,
                            source=source,
                            docstring=_preceding_doc_comment(source, sub),
                            visibility=_visibility_of(source, sub),
                        )
                    )
    elif node.type == "function_item":
        name_node = _name_of(node)
        if name_node is None:
            return
        rows.append(
            _row(
                name=_text(source, name_node),
                kind="function",
                file_path=file_path,
                node=node,
                source=source,
                docstring=_preceding_doc_comment(source, node),
                visibility=_visibility_of(source, node),
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
