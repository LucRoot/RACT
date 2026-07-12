# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""AST-based structural normalization for Python source.

Detects duplication that survives identifier renaming. The normalized form
strips docstrings, comments, type annotations, and alpha-renames every
identifier to a canonical token. Two pieces of code that differ only by
symbol names become byte-identical after normalization.

LR:: This is the anti-rot signal that compression-based detectors cannot
provide. Compression sees bytes; normalization sees structure. Used together
they catch both verbatim copies and copy-and-rename clones.
"""

import ast
import hashlib
from difflib import SequenceMatcher


class _Normalizer(ast.NodeTransformer):
    """Transform an AST so identifiers become canonical placeholders."""

    def __init__(self) -> None:
        # Stack of scope mappings: original name -> canonical name.
        self._scopes: list[dict[str, str]] = [{}]
        # Counters per kind, global for deterministic ordering.
        self._counters: dict[str, int] = {
            "func": 0,
            "class": 0,
            "arg": 0,
            "name": 0,
            "attr": 0,
        }

    def _canonical(self, kind: str) -> str:
        idx = self._counters[kind]
        self._counters[kind] = idx + 1
        prefix = {
            "func": "_f",
            "class": "_c",
            "arg": "_a",
            "name": "_v",
            "attr": "_at",
        }[kind]
        return f"{prefix}{idx}"

    def _bind(self, name: str) -> str:
        """Record *name* as bound in the current scope and return canonical."""
        canonical = self._canonical("name")
        self._scopes[-1][name] = canonical
        return canonical

    def _lookup(self, name: str) -> str:
        """Resolve *name* through the scope stack; fall back to fresh canonical."""
        for scope in reversed(self._scopes):
            if name in scope:
                return scope[name]
        # Free variable or builtin: assign a fresh canonical name. This keeps
        # structurally identical free references identical.
        return self._bind(name)

    def _push_scope(self) -> None:
        self._scopes.append({})

    def _pop_scope(self) -> None:
        self._scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # noqa: N802
        self._push_scope()
        node.name = self._canonical("func")
        node.args = self.visit(node.args)  # type: ignore[assignment]
        node.body = self._visit_body(node.body)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.returns = None
        self._pop_scope()
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # noqa: N802
        self._push_scope()
        node.name = self._canonical("func")
        node.args = self.visit(node.args)  # type: ignore[assignment]
        node.body = self._visit_body(node.body)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.returns = None
        self._pop_scope()
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # noqa: N802
        self._push_scope()
        node.name = self._canonical("class")
        node.bases = [self.visit(b) for b in node.bases]
        node.keywords = [self.visit(k) for k in node.keywords]
        node.body = self._visit_body(node.body)
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        self._pop_scope()
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:  # noqa: N802
        self._push_scope()
        node.args = self.visit(node.args)  # type: ignore[assignment]
        node.body = self.visit(node.body)
        self._pop_scope()
        return node

    def visit_comprehension(self, node: ast.comprehension) -> ast.comprehension:
        self._push_scope()
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.ifs = [self.visit(if_) for if_ in node.ifs]
        self._pop_scope()
        return node

    def visit_ListComp(self, node: ast.ListComp) -> ast.AST:  # noqa: N802
        node.elt = self.visit(node.elt)
        node.generators = [self.visit(g) for g in node.generators]
        return node

    def visit_SetComp(self, node: ast.SetComp) -> ast.AST:  # noqa: N802
        node.elt = self.visit(node.elt)
        node.generators = [self.visit(g) for g in node.generators]
        return node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> ast.AST:  # noqa: N802
        node.elt = self.visit(node.elt)
        node.generators = [self.visit(g) for g in node.generators]
        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.AST:  # noqa: N802
        node.key = self.visit(node.key)
        node.value = self.visit(node.value)
        node.generators = [self.visit(g) for g in node.generators]
        return node

    def visit_arguments(self, node: ast.arguments) -> ast.arguments:
        # Map args in source order.
        for arg in node.args:
            arg.arg = self._canonical("arg")
            arg.annotation = None
        for arg in node.posonlyargs:
            arg.arg = self._canonical("arg")
            arg.annotation = None
        for arg in node.kwonlyargs:
            arg.arg = self._canonical("arg")
            arg.annotation = None
        if node.vararg:
            node.vararg.arg = self._canonical("arg")
            node.vararg.annotation = None
        if node.kwarg:
            node.kwarg.arg = self._canonical("arg")
            node.kwarg.annotation = None
        # Defaults may reference outer scope; visit them in outer scope.
        node.defaults = [self.visit(d) for d in node.defaults]
        node.kw_defaults = [
            self.visit(d) if d is not None else None for d in node.kw_defaults
        ]
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.annotation = None
        return node

    def visit_Name(self, node: ast.Name) -> ast.Name:  # noqa: N802
        node.id = self._lookup(node.id)
        return node

    def visit_Attribute(self, node: ast.Attribute) -> ast.Attribute:  # noqa: N802
        node.value = self.visit(node.value)
        node.attr = self._canonical("attr")
        return node

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:  # noqa: N802
        # Drop annotation. Annotation-only statements have no runtime effect.
        if node.value is None:
            return ast.Pass()
        return ast.Assign(
            targets=[self.visit(node.target)],
            value=self.visit(node.value),
            lineno=getattr(node, "lineno", 0),
            col_offset=getattr(node, "col_offset", 0),
        )

    def visit_Expr(self, node: ast.Expr) -> ast.AST | None:  # noqa: N802
        inner = node.value
        # Strip module/class/function-level docstrings.
        if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            return None
        return self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> ast.AST:  # noqa: N802
        for alias in node.names:
            alias.name = self._bind(alias.name)
            if alias.asname:
                alias.asname = self._bind(alias.asname)
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:  # noqa: N802
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[-1]
            canonical = self._bind(local)
            alias.name = canonical
            alias.asname = None
        return node

    def visit_NamedExpr(self, node: ast.NamedExpr) -> ast.NamedExpr:  # noqa: N802
        node.target = self.visit(node.target)
        node.value = self.visit(node.value)
        return node

    def visit_For(self, node: ast.For) -> ast.For:  # noqa: N802
        self._push_scope()
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.body = self._visit_body(node.body)
        node.orelse = self._visit_body(node.orelse)
        self._pop_scope()
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:  # noqa: N802
        self._push_scope()
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.body = self._visit_body(node.body)
        node.orelse = self._visit_body(node.orelse)
        self._pop_scope()
        return node

    def visit_With(self, node: ast.With) -> ast.With:  # noqa: N802
        self._push_scope()
        for item in node.items:
            item.context_expr = self.visit(item.context_expr)
            if item.optional_vars:
                item.optional_vars = self.visit(item.optional_vars)
        node.body = self._visit_body(node.body)
        self._pop_scope()
        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> ast.AsyncWith:  # noqa: N802
        self._push_scope()
        for item in node.items:
            item.context_expr = self.visit(item.context_expr)
            if item.optional_vars:
                item.optional_vars = self.visit(item.optional_vars)
        node.body = self._visit_body(node.body)
        self._pop_scope()
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.ExceptHandler:  # noqa: N802
        self._push_scope()
        if node.name:
            self._bind(node.name)
            node.name = self._scopes[-1][node.name]
        if node.type:
            node.type = self.visit(node.type)
        node.body = self._visit_body(node.body)
        self._pop_scope()
        return node

    def _visit_body(self, body: list[ast.stmt]) -> list[ast.stmt]:
        """Visit body statements and drop None results (stripped docstrings)."""
        result: list[ast.stmt] = []
        for stmt in body:
            visited = self.visit(stmt)
            if isinstance(visited, list):
                result.extend(v for v in visited if v is not None)
            elif visited is not None:
                result.append(visited)
        return result

    def _visit_expr_as_none(self) -> None:
        return None


def normalize_python(source: str) -> str:
    """Return a structural-normalized form of *source*.

    The output is valid Python where every identifier has been replaced by a
    canonical placeholder. Two code fragments that differ only by symbol names
    produce identical normalized strings.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Cannot normalize invalid Python: {exc}") from exc
    normalizer = _Normalizer()
    tree = normalizer.visit(tree)
    return ast.unparse(tree)


def structural_hash(source: str) -> str | None:
    """Return a hash of the AST-normalized form of *source*.

    Two sources that differ only by identifier names share the same hash.
    Returns None for invalid Python.
    """
    try:
        return hashlib.sha256(normalize_python(source).encode("utf-8")).hexdigest()
    except ValueError:
        return None


def structural_similarity(a: str, b: str) -> float:
    """Return structural similarity in [0.0, 1.0] for two Python sources.

    1.0 means the sources are structurally identical under alpha-renaming.
    0.0 means they share no structure. Invalid sources return 0.0.
    """
    try:
        norm_a = normalize_python(a)
        norm_b = normalize_python(b)
    except ValueError:
        return 0.0
    return structural_similarity_normalized(norm_a, norm_b)


def structural_similarity_normalized(norm_a: str, norm_b: str) -> float:
    """Return structural similarity for already-normalized Python sources."""
    if norm_a == norm_b:
        return 1.0

    len_a, len_b = len(norm_a), len(norm_b)
    # Near-duplicates have similar sizes; avoid expensive comparison for
    # modules that are clearly not copies (e.g., cli.py vs. a tiny module).
    if len_a == 0 or len_b == 0 or max(len_a, len_b) / min(len_a, len_b) > 2.5:
        return 0.0

    # SequenceMatcher is O(n*m); for large normalized sources use a cheaper
    # token-level Jaccard estimate that still catches near-duplicates.
    _LARGE = 10_000
    if len_a > _LARGE or len_b > _LARGE:
        tokens_a = set(norm_a.split())
        tokens_b = set(norm_b.split())
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)

    return SequenceMatcher(None, norm_a, norm_b).ratio()


# RACT 0.1.1 - Trust and Tooling
