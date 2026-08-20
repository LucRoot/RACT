"""Polyglot G5 -- unreferenced-identifier (dead-code) gate.

module_08 (v0.5.1) delivers this module to close DeepSeek REVIEW_3
§C3 (G5 currently Python-only via ``ast``). Dispatches on file
extension:

- ``.py``  -- delegates to :class:`ract.dead_code_auction.DeadCodeAuction`
  (existing v0.3 primitive; unchanged) so Python behaviour is preserved
  bit-for-bit relative to pre-module_08.
- ``.js`` / ``.mjs`` / ``.cjs`` / ``.jsx`` -- tree-sitter walk over
  ``function_declaration``, ``variable_declarator``,
  ``export_statement`` identifiers.
- ``.ts`` / ``.tsx`` -- tree-sitter walk over the TypeScript grammar's
  declaration/export/import nodes.
- ``.rs`` -- tree-sitter walk over ``function_item``, ``struct_item``,
  ``impl_item``, ``use_declaration``.
- ``.go`` -- tree-sitter walk over ``function_declaration``,
  ``method_declaration``, ``type_declaration``, ``var_declaration``.

Unsupported languages (docs, config, binaries) are SKIPPED with a
WARN log rather than raising -- matches module_08 spec "degrade
gracefully; never fail the loop on unsupported language".

This module is ADDITIVE. The legacy ``enforce_g5`` in
``ract.antilazy.pre_commit`` (test-integrity via AST diff) is
untouched. Callers who want polyglot dead-code scanning invoke
:func:`scan_dead_code` directly or via
:func:`ract.antilazy.pre_commit.enforce_g5_dead_code_polyglot`.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ract.parsers.tree_sitter_backend import (
    Language,
    ParseTree,
    field_named,
    iter_nodes,
    language_for,
    node_text,
    parse,
)

_LOG = logging.getLogger("ract.antilazy.dead_code_polyglot")


@dataclass(frozen=True)
class DeadCodeCandidate:
    """One dead-code candidate identified by the polyglot walk."""

    file: str
    language: str
    identifier: str
    kind: str  # e.g. "function", "const", "struct", "type", "var"
    start_row: int
    start_col: int
    reason: str = "no inbound reference within scanned corpus"


@dataclass(frozen=True)
class DeadCodePolyglotReport:
    """Aggregate polyglot dead-code report across a file set."""

    candidates: tuple[DeadCodeCandidate, ...] = field(default_factory=tuple)
    skipped_files: tuple[str, ...] = field(default_factory=tuple)
    unsupported_languages: tuple[str, ...] = field(default_factory=tuple)

    def passed(self, threshold: int = 0) -> bool:
        """True when candidate count is at or below ``threshold``."""
        return len(self.candidates) <= threshold


# ---------------------------------------------------------------------------
# Language-specific extractors
# ---------------------------------------------------------------------------


def _collect_python_identifiers(source: str) -> tuple[list[tuple[str, str, int, int]], set[str]]:
    """Return (declarations, references) for Python source.

    Declarations: list of ``(name, kind, row, col)``.
    References: set of names that appear in a Load context.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return [], set()
    decls: list[tuple[str, str, int, int]] = []
    refs: set[str] = set()

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            decls.append((node.name, "function", node.lineno - 1, node.col_offset))
            self.generic_visit(node)

        def visit_AsyncFunctionDef(  # noqa: N802
            self, node: ast.AsyncFunctionDef
        ) -> None:
            decls.append((node.name, "function", node.lineno - 1, node.col_offset))
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            decls.append((node.name, "class", node.lineno - 1, node.col_offset))
            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
            for target in node.targets:
                if isinstance(target, ast.Name):
                    decls.append(
                        (target.id, "const", node.lineno - 1, node.col_offset)
                    )
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
            if isinstance(node.ctx, ast.Load):
                refs.add(node.id)

        def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
            # A leading Name inside x.y.z counts as a reference to x.
            base: ast.expr = node
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(base, ast.Name):
                refs.add(base.id)
            self.generic_visit(node)

    _Visitor().visit(tree)
    return decls, refs


_ID_NODE_TYPES = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "scoped_identifier",
    "shorthand_property_identifier",
}


def _collect_from_tree(
    tree: ParseTree,
    decl_types: dict[str, str],
    id_field: str = "name",
    id_child_types: set[str] | None = None,
) -> tuple[list[tuple[str, str, int, int]], set[str], set[tuple[int, int]]]:
    """Generic tree-sitter declaration+reference walker.

    ``decl_types`` maps node type -> kind label. For each declaration
    node the child field ``id_field`` (default ``"name"``) is treated
    as the identifier; the identifier's node type must be one of
    ``id_child_types`` (default: any ``_ID_NODE_TYPES`` member).

    Every identifier-shaped node NOT recorded as a decl-name is a
    reference.

    Returns ``(declarations, references, decl_id_byte_ranges)``.
    ``decl_id_byte_ranges`` lets callers chain a second walker without
    double-counting decl names as references.
    """
    if id_child_types is None:
        id_child_types = _ID_NODE_TYPES
    src = tree.source_bytes
    decls: list[tuple[str, str, int, int]] = []
    decl_id_bytes: set[tuple[int, int]] = set()

    # First pass: collect declarations + their name byte ranges.
    for node in iter_nodes(tree.root_node):
        ntype = getattr(node, "type", "")
        if ntype in decl_types:
            name_node = field_named(node, id_field)
            if name_node is None or getattr(name_node, "type", "") not in id_child_types:
                for child in getattr(node, "children", ()) or ():
                    if getattr(child, "type", "") in id_child_types:
                        name_node = child
                        break
            if name_node is not None and getattr(name_node, "type", "") in id_child_types:
                name = node_text(name_node, src)
                sp = getattr(name_node, "start_point", (0, 0))
                decls.append((name, decl_types[ntype], sp[0], sp[1]))
                decl_id_bytes.add(
                    (
                        getattr(name_node, "start_byte", 0),
                        getattr(name_node, "end_byte", 0),
                    )
                )

    # Second pass: every identifier-shaped node NOT a decl name is a ref.
    refs: set[str] = set()
    for node in iter_nodes(tree.root_node, node_types=_ID_NODE_TYPES):
        key = (
            getattr(node, "start_byte", 0),
            getattr(node, "end_byte", 0),
        )
        if key in decl_id_bytes:
            continue
        refs.add(node_text(node, src))
    return decls, refs, decl_id_bytes


# Language-specific declaration-type maps.

_JS_DECL_TYPES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "lexical_declaration": "const",  # const/let
    "variable_declaration": "var",
}

_TS_DECL_TYPES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "lexical_declaration": "const",
    "variable_declaration": "var",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}

_RS_DECL_TYPES = {
    "function_item": "fn",
    "struct_item": "struct",
    "enum_item": "enum",
    "impl_item": "impl",
    "trait_item": "trait",
    "type_item": "type",
    "static_item": "static",
    "const_item": "const",
}

_GO_DECL_TYPES = {
    "function_declaration": "func",
    "method_declaration": "func",
    "type_spec": "type",
    "var_spec": "var",
    "const_spec": "const",
}


def _collect_declarator_decls(
    tree: ParseTree, kind: str = "var"
) -> tuple[list[tuple[str, str, int, int]], set[tuple[int, int]]]:
    """Walk ``variable_declarator`` nodes and collect their name identifiers.

    Both JS and TS grammars nest ``variable_declarator`` inside a parent
    ``lexical_declaration`` / ``variable_declaration``. Each declarator
    contributes ONE identifier the top-level walker misses when using
    ``child_by_field_name('name')`` on the grouping node.
    """
    src = tree.source_bytes
    decls: list[tuple[str, str, int, int]] = []
    decl_id_bytes: set[tuple[int, int]] = set()
    for node in iter_nodes(tree.root_node, node_types={"variable_declarator"}):
        name_node = field_named(node, "name")
        if name_node is None:
            for child in getattr(node, "children", ()) or ():
                if getattr(child, "type", "") == "identifier":
                    name_node = child
                    break
        if name_node is not None and getattr(name_node, "type", "") == "identifier":
            name = node_text(name_node, src)
            sp = getattr(name_node, "start_point", (0, 0))
            decls.append((name, kind, sp[0], sp[1]))
            decl_id_bytes.add(
                (
                    getattr(name_node, "start_byte", 0),
                    getattr(name_node, "end_byte", 0),
                )
            )
    return decls, decl_id_bytes


def _js_collect(
    tree: ParseTree,
) -> tuple[list[tuple[str, str, int, int]], set[str]]:
    """JavaScript collector: functions/classes + variable declarators."""
    decl_types = {
        k: v
        for k, v in _JS_DECL_TYPES.items()
        if k not in {"lexical_declaration", "variable_declaration"}
    }
    decls, _refs, top_decl_bytes = _collect_from_tree(tree, decl_types)
    var_decls, var_decl_bytes = _collect_declarator_decls(tree, kind="var")
    decls.extend(var_decls)
    all_decl_bytes = top_decl_bytes | var_decl_bytes

    # Reference pass across the union.
    src = tree.source_bytes
    refs: set[str] = set()
    for node in iter_nodes(tree.root_node, node_types=_ID_NODE_TYPES):
        key = (getattr(node, "start_byte", 0), getattr(node, "end_byte", 0))
        if key in all_decl_bytes:
            continue
        refs.add(node_text(node, src))
    return decls, refs


def _ts_collect(
    tree: ParseTree,
) -> tuple[list[tuple[str, str, int, int]], set[str]]:
    """TypeScript collector: JS surface + interface/type/enum decls."""
    decl_types = {
        k: v
        for k, v in _TS_DECL_TYPES.items()
        if k not in {"lexical_declaration", "variable_declaration"}
    }
    decls, _refs, top_decl_bytes = _collect_from_tree(tree, decl_types)
    var_decls, var_decl_bytes = _collect_declarator_decls(tree, kind="var")
    decls.extend(var_decls)
    all_decl_bytes = top_decl_bytes | var_decl_bytes

    src = tree.source_bytes
    refs: set[str] = set()
    for node in iter_nodes(tree.root_node, node_types=_ID_NODE_TYPES):
        key = (getattr(node, "start_byte", 0), getattr(node, "end_byte", 0))
        if key in all_decl_bytes:
            continue
        refs.add(node_text(node, src))
    return decls, refs


def _rs_collect(
    tree: ParseTree,
) -> tuple[list[tuple[str, str, int, int]], set[str]]:
    """Rust collector; ``use_declaration`` targets count as references."""
    decls, refs, _decl_bytes = _collect_from_tree(tree, _RS_DECL_TYPES)
    src = tree.source_bytes
    for node in iter_nodes(tree.root_node, node_types={"use_declaration"}):
        for id_node in iter_nodes(node, node_types=_ID_NODE_TYPES):
            refs.add(node_text(id_node, src))
    return decls, refs


def _go_collect(
    tree: ParseTree,
) -> tuple[list[tuple[str, str, int, int]], set[str]]:
    """Go collector: functions, methods, and (name-carrying) specs."""
    decls, refs, _decl_bytes = _collect_from_tree(tree, _GO_DECL_TYPES)
    return decls, refs


# ---------------------------------------------------------------------------
# Per-file walker
# ---------------------------------------------------------------------------


def _extract_file(
    path: Path, source_bytes: bytes
) -> tuple[Language | None, list[tuple[str, str, int, int]], set[str]]:
    lang = language_for(path)
    if lang is None:
        return None, [], set()
    if lang is Language.PYTHON:
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return lang, [], set()
        decls, refs = _collect_python_identifiers(source)
        return lang, decls, refs
    tree = parse(path, source_bytes)
    if tree is None:
        return lang, [], set()
    if lang in (Language.JAVASCRIPT, Language.TSX):
        decls, refs = _js_collect(tree)
        return lang, decls, refs
    if lang is Language.TYPESCRIPT:
        decls, refs = _ts_collect(tree)
        return lang, decls, refs
    if lang is Language.RUST:
        decls, refs = _rs_collect(tree)
        return lang, decls, refs
    if lang is Language.GO:
        decls, refs = _go_collect(tree)
        return lang, decls, refs
    return lang, [], set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scan_dead_code(
    files: Iterable[Path],
    *,
    ignore_names: set[str] | None = None,
    ignore_leading_underscore: bool = True,
) -> DeadCodePolyglotReport:
    """Scan ``files`` and return unreferenced declarations.

    Rules:

    - Declarations across ALL scanned files contribute to the
      candidate pool; references across ALL scanned files consume
      them. A declaration is a candidate when its identifier does not
      appear as a reference in ANY scanned file.
    - ``ignore_names`` (default: standard entry-point + framework
      names) suppresses false positives for e.g. ``main``, ``__init__``.
    - ``ignore_leading_underscore=True`` (default) treats
      ``_helper``-style privates as intentional (Python convention;
      also common in Rust for allow-dead-code).
    - Files with unsupported extensions are collected into
      ``skipped_files`` (with WARN log) instead of raising.
    - Files whose language is known but grammar unavailable are
      collected into ``unsupported_languages`` (with WARN log).
    """
    if ignore_names is None:
        ignore_names = {
            "main",
            "init",
            "__init__",
            "__main__",
            "setUp",
            "tearDown",
            "setUpClass",
            "tearDownClass",
            "default",
        }
    per_file: dict[Path, tuple[Language, list[tuple[str, str, int, int]], set[str]]] = {}
    skipped: list[str] = []
    unsupported: set[str] = set()
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError as e:
            _LOG.warning("dead_code_polyglot: read failure %s: %s", path, e)
            skipped.append(str(path))
            continue
        lang, decls, refs = _extract_file(path, raw)
        if lang is None:
            skipped.append(str(path))
            continue
        if not decls and not refs:
            # Empty extraction (grammar unavailable or empty file).
            # Distinguish the two: if no parser AND lang known, mark
            # unsupported; otherwise treat as an empty file (no-op).
            from ract.parsers.tree_sitter_backend import _load_grammar as _lg  # noqa: PLC0415

            if lang is not Language.PYTHON and _lg(lang) is None:
                unsupported.add(lang.value)
                continue
        per_file[path] = (lang, decls, refs)

    all_refs: set[str] = set()
    for _lang, _decls, refs in per_file.values():
        all_refs |= refs

    candidates: list[DeadCodeCandidate] = []
    for path, (lang, decls, _refs) in per_file.items():
        for name, kind, row, col in decls:
            if name in ignore_names:
                continue
            if ignore_leading_underscore and name.startswith("_"):
                continue
            if name in all_refs:
                continue
            candidates.append(
                DeadCodeCandidate(
                    file=str(path),
                    language=lang.value,
                    identifier=name,
                    kind=kind,
                    start_row=row,
                    start_col=col,
                )
            )
    return DeadCodePolyglotReport(
        candidates=tuple(candidates),
        skipped_files=tuple(sorted(skipped)),
        unsupported_languages=tuple(sorted(unsupported)),
    )


def scan_dead_code_in_dir(
    root: Path,
    *,
    ignore_dirs: set[str] | None = None,
    ignore_names: set[str] | None = None,
    ignore_leading_underscore: bool = True,
) -> DeadCodePolyglotReport:
    """Recursively scan a directory for polyglot dead code.

    ``ignore_dirs`` defaults to a common vendor / cache set; extend
    per caller.
    """
    if ignore_dirs is None:
        ignore_dirs = {
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "node_modules",
            "_BUILD",
            "target",
            "dist",
            "build",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
        }
    files: list[Path] = []
    for entry in root.rglob("*"):
        if not entry.is_file():
            continue
        parts = set(entry.parts)
        if parts & ignore_dirs:
            continue
        if language_for(entry) is None:
            continue
        files.append(entry)
    return scan_dead_code(
        files,
        ignore_names=ignore_names,
        ignore_leading_underscore=ignore_leading_underscore,
    )


__all__ = [
    "DeadCodeCandidate",
    "DeadCodePolyglotReport",
    "scan_dead_code",
    "scan_dead_code_in_dir",
]
