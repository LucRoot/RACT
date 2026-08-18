"""Python tree-sitter parser for the symbol index.

Chunking rule (master spec section "Chunk discipline / AST chunking
rules"):

- module, class, function, method, decorator+function group.
- Docstrings stay attached (first string statement inside the body).
- Module-level type aliases are their own chunks. Detected as a
  module-level ``assignment`` whose left-hand side is a single
  identifier that starts with an uppercase letter, OR whose right-
  hand side is a call to ``TypeVar`` / ``NewType`` / a subscripted
  ``typing`` construct.

Nested definitions (a function inside a function) DO NOT surface as
top-level symbols; only class methods promote up because their parent
is a class and that mapping is a first-class chunk boundary.

Grammar pin: ``tree-sitter-python`` 0.25.x. A mismatched version at
import raises :class:`~ract.memory.languages.GrammarVersionMismatchError`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

import tree_sitter_python

from ract.core.module_identity import _module_knot, register_module_knot
from ract.memory.languages import GrammarVersionMismatchError, _installed_version
from ract.memory.symbol_index import SymbolRow


LANGUAGE_LABEL: str = "python"
SUPPORTED_GRAMMAR_VERSION: str = "0.25.0"
"""Pinned tree-sitter-python distribution version."""

_TYPE_HINT_NAMES: frozenset[str] = frozenset(
    {"TypeVar", "NewType", "TypeAlias", "Union", "Optional", "Literal", "Callable"}
)


def _check_grammar_version() -> None:
    installed = _installed_version("tree-sitter-python")
    # Accept exact match on 0.25.x — the chunking rules land on the
    # 0.25 grammar's node kind vocabulary. A 0.24 or 0.26 renamed
    # kind would slip through unless we pin.
    if not installed.startswith("0.25."):
        raise GrammarVersionMismatchError(
            language=LANGUAGE_LABEL,
            expected=SUPPORTED_GRAMMAR_VERSION,
            observed=installed,
        )


_check_grammar_version()
_LANGUAGE = Language(tree_sitter_python.language())
_PARSER = Parser(_LANGUAGE)


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _child_by_field(node: Any, field: str) -> Any | None:
    return node.child_by_field_name(field)


def _extract_docstring(source: bytes, body_node: Any) -> str | None:
    """First string statement inside a body is the docstring."""
    for child in body_node.children:
        if child.type == "expression_statement":
            for grand in child.children:
                if grand.type == "string":
                    return _node_text(source, grand).strip("'\" \n\t\r")
                if grand.type == "concatenated_string":
                    return _node_text(source, grand).strip("'\" \n\t\r")
            return None
        if child.type in ("comment",):
            continue
        return None
    return None


def _hash_bytes(source: bytes, node: Any) -> str:
    return hashlib.sha256(source[node.start_byte : node.end_byte]).hexdigest()


def _tokens_of(source: bytes, node: Any) -> int:
    text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    return len(text.split())


def _visibility(name: str) -> str:
    return "private" if name.startswith("_") else "public"


def _signature(source: bytes, node: Any) -> str:
    """Header line of the declaration (first line, trimmed)."""
    text = source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
    return text.split("\n", 1)[0].rstrip()


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
        visibility=visibility if visibility is not None else _visibility(name),
        parent_symbol_id=None,
        language=LANGUAGE_LABEL,
        content_hash=_hash_bytes(source, node),
        token_count=_tokens_of(source, node),
        updated_at=None,
    )


def _looks_like_type_alias_rhs(rhs_text: str) -> bool:
    """Right-hand side smells like a type expression.

    Heuristic — catches common shapes without a full type analysis:
    ``Union[...]``, ``Optional[...]``, ``list[int]``, ``Callable[...]``,
    a call to ``TypeVar`` / ``NewType`` / ``TypeAlias``.
    """
    if any(name in rhs_text for name in _TYPE_HINT_NAMES):
        return True
    stripped = rhs_text.strip()
    if "[" in stripped and stripped.endswith("]"):
        head = stripped.split("[", 1)[0].strip()
        # ``list[int]``, ``dict[str, int]`` etc.
        if head and head[0].isalpha():
            return True
    return False


def _classify_module_assignment(source: bytes, node: Any) -> tuple[str, str] | None:
    """Return ``(name, kind)`` for a module-level assignment we index.

    Returns ``None`` for shapes we skip (tuple targets, chained
    assignments, augmented assignments).

    An annotated assignment carries an explicit type annotation on the
    ``type`` field. When the annotation is exactly ``TypeAlias`` the
    row is emitted as ``type`` regardless of the LHS casing (Second
    Pass Q1: ``X: TypeAlias = int`` where LHS ``X`` is lower-case
    would otherwise be skipped by the uppercase-first heuristic).
    """
    lhs = _child_by_field(node, "left")
    rhs = _child_by_field(node, "right")
    if lhs is None or rhs is None:
        return None
    if lhs.type != "identifier":
        return None
    name = _node_text(source, lhs)
    rhs_text = _node_text(source, rhs)
    annotation = _child_by_field(node, "type")
    if annotation is not None:
        annotation_text = _node_text(source, annotation).strip()
        if annotation_text == "TypeAlias" or annotation_text.endswith(".TypeAlias"):
            return name, "type"
    # ALL_CAPS_WITH_UNDERSCORES is the Python constant convention and
    # takes precedence over the uppercase-first heuristic below (which
    # is meant for mixed-case type aliases like ``MyType``).
    if _is_all_caps(name):
        return name, "constant"
    if name[:1].isupper() or _looks_like_type_alias_rhs(rhs_text):
        return name, "type"
    return None


def _pep695_type_alias(source: bytes, node: Any) -> tuple[str, str] | None:
    """Return ``(name, kind)`` for a PEP 695 ``type X = ...`` statement.

    The tree-sitter-python 0.23+ grammar exposes the shape as a
    ``type_alias_statement`` node with the alias name as the first
    ``type`` field child holding an ``identifier``. Second Pass Q1
    (CONFIRMED): the parser previously walked only ``assignment`` at
    module scope and dropped every PEP 695 alias silently.
    """
    # The alias name lives at the first ``type`` field child that
    # wraps an ``identifier``. Structurally: type_alias_statement ->
    # (keyword `type`, type[name=identifier], `=`, type[value]).
    alias_name: str | None = None
    for child in node.children:
        if child.type != "type":
            continue
        for grand in child.children:
            if grand.type == "identifier":
                alias_name = _node_text(source, grand)
                break
        if alias_name is not None:
            break
    if alias_name is None:
        return None
    return alias_name, "type"


def _is_all_caps(name: str) -> bool:
    """Return True for ALL_CAPS constant naming (underscores + digits allowed)."""
    stripped = name.lstrip("_")
    if not stripped:
        return False
    if not any(ch.isalpha() for ch in stripped):
        return False
    for ch in stripped:
        if ch.isalpha() and not ch.isupper():
            return False
    return True


def parse(source: bytes, path: Path) -> list[SymbolRow]:
    """Parse ``source`` and return the flat symbol list for ``path``.

    Emitted kinds: ``function``, ``class``, ``method``, ``type``,
    ``constant``. Nested-in-function definitions do not surface.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            f"python.parse: source must be bytes-like; got {type(source).__name__}"
        )
    tree = _PARSER.parse(bytes(source))
    file_path = str(path)
    rows: list[SymbolRow] = []
    root = tree.root_node
    for child in root.children:
        if child.type == "function_definition":
            name_node = _child_by_field(child, "name")
            body_node = _child_by_field(child, "body")
            if name_node is None or body_node is None:
                continue
            name = _node_text(source, name_node)
            rows.append(
                _row(
                    name=name,
                    kind="function",
                    file_path=file_path,
                    node=child,
                    source=source,
                    docstring=_extract_docstring(source, body_node),
                )
            )
        elif child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is None:
                continue
            name_node = _child_by_field(inner, "name")
            body_node = _child_by_field(inner, "body")
            if name_node is None or body_node is None:
                continue
            name = _node_text(source, name_node)
            kind = "function" if inner.type == "function_definition" else "class"
            rows.append(
                _row(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    node=child,
                    source=source,
                    docstring=_extract_docstring(source, body_node),
                )
            )
            if kind == "class":
                rows.extend(_class_methods(source, file_path, body_node))
        elif child.type == "class_definition":
            name_node = _child_by_field(child, "name")
            body_node = _child_by_field(child, "body")
            if name_node is None or body_node is None:
                continue
            name = _node_text(source, name_node)
            rows.append(
                _row(
                    name=name,
                    kind="class",
                    file_path=file_path,
                    node=child,
                    source=source,
                    docstring=_extract_docstring(source, body_node),
                )
            )
            rows.extend(_class_methods(source, file_path, body_node))
        elif child.type == "expression_statement":
            for grand in child.children:
                if grand.type == "assignment":
                    got = _classify_module_assignment(source, grand)
                    if got is None:
                        continue
                    name, kind = got
                    rows.append(
                        _row(
                            name=name,
                            kind=kind,
                            file_path=file_path,
                            node=grand,
                            source=source,
                        )
                    )
        elif child.type == "type_alias_statement":
            got = _pep695_type_alias(source, child)
            if got is None:
                continue
            name, kind = got
            rows.append(
                _row(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    node=child,
                    source=source,
                )
            )
    return rows


def _class_methods(source: bytes, file_path: str, body_node: Any) -> list[SymbolRow]:
    """Emit one row per ``def`` (or ``async def``) inside a class body."""
    out: list[SymbolRow] = []
    for child in body_node.children:
        target = child
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is None:
                continue
            target = child
            def_node = inner
        elif child.type == "function_definition":
            def_node = child
        else:
            continue
        name_node = _child_by_field(def_node, "name")
        body = _child_by_field(def_node, "body")
        if name_node is None or body is None:
            continue
        name = _node_text(source, name_node)
        out.append(
            _row(
                name=name,
                kind="method",
                file_path=file_path,
                node=target,
                source=source,
                docstring=_extract_docstring(source, body),
            )
        )
    return out


__all__ = [
    "LANGUAGE_LABEL",
    "SUPPORTED_GRAMMAR_VERSION",
    "parse",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
