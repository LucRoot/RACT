# Rooted by Dr. Lucas Root, Ph.D.
"""AST-normalized canonical similarity for anti-rot detection.

LR:: LLMs commonly duplicate a module and rename its identifiers; lexical
similarity (compression ratio) misses this because every renamed token is a
fresh byte sequence. By alpha-renaming identifiers to canonical tokens and
dropping docstrings/annotations before comparison, a copy-and-rename clone
collapses to near-identical structure and becomes detectable.
"""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import ast
import hashlib


class _Canonicalizer(ast.NodeTransformer):
    """Alpha-rename identifiers and strip docstrings/annotations."""

    def __init__(self) -> None:
        self._name_map: dict[str, str] = {}
        self._var_count = 0
        self._func_count = 0
        self._class_count = 0

    def _canonical(self, original: str, kind: str) -> str:
        if original in self._name_map:
            return self._name_map[original]
        if kind == "func":
            token = f"f{self._func_count}"
            self._func_count += 1
        elif kind == "cls":
            token = f"c{self._class_count}"
            self._class_count += 1
        else:
            token = f"v{self._var_count}"
            self._var_count += 1
        self._name_map[original] = token
        return token

    def _strip_docstring(self, body: list[ast.stmt]) -> list[ast.stmt]:
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            return body[1:]
        return body

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = self._canonical(node.name, "func")
        node.returns = None
        for arg in list(node.args.args) + list(node.args.kwonlyargs):
            arg.annotation = None
        if node.args.vararg is not None:
            node.args.vararg.annotation = None
        if node.args.kwarg is not None:
            node.args.kwarg.annotation = None
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = self._canonical(node.name, "func")
        node.returns = None
        for arg in list(node.args.args) + list(node.args.kwonlyargs):
            arg.annotation = None
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = self._canonical(node.name, "cls")
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.annotation = None
        node.arg = self._canonical(node.arg, "var")
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = self._canonical(node.id, "var")
        return node

    def visit_Module(self, node: ast.Module) -> ast.AST:
        node.body = self._strip_docstring(node.body)
        self.generic_visit(node)
        return node


def canonicalize(source: str) -> str:
    """Return a canonical, identifier-renamed rendering of ``source``.

    Module/function/class docstrings and type annotations are stripped. Comments
    are dropped by the parser. If the source is not valid Python, the original
    text is returned unchanged so callers can fall back to lexical comparison.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    canonicalizer = _Canonicalizer()
    transformed = canonicalizer.visit(tree)
    ast.fix_missing_locations(transformed)
    return ast.unparse(transformed)


def canonical_hash(source: str) -> str:
    """Return a stable hash of the canonical form for fast equality checks."""
    return hashlib.sha256(canonicalize(source).encode("utf-8")).hexdigest()


def canonical_similarity(a: str, b: str) -> float:
    """Return Jaccard similarity over canonical tokens in [0, 1].

    Tokenization is over whitespace-split canonical source; this is robust to
    formatting differences while remaining sensitive to structural edits.
    """
    a_tokens = set(canonicalize(a).split())
    b_tokens = set(canonicalize(b).split())
    if not a_tokens and not b_tokens:
        return 1.0
    union = a_tokens | b_tokens
    if not union:
        return 1.0
    return len(a_tokens & b_tokens) / len(union)
