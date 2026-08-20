"""Polyglot G6 -- test-copy-paste detector.

module_08 (v0.5.1) delivers this module to close DeepSeek REVIEW_3
§C3 (G6 currently Python-only via ``ast``). Detects near-identical
test bodies -- the "copy the passing test, tweak the name" anti-
pattern the ALM reward channel encourages when the model is graded
by suite pass-rate alone.

Fingerprinting shape (per test):

1. Extract each test function's *body* AST/tree.
2. Token-normalise: strip identifier spelling (all identifiers -> ``X``);
   strip literal values (all string/number literals -> ``L``); collapse
   whitespace. This makes ``assert x == 1`` and ``assert y == 42``
   collide as ``assert X == L``.
3. Compute the normalised-token multiset per test.
4. For every pair, compute Jaccard similarity over the multiset.
5. Pairs above ``jaccard_threshold`` (default 0.85) with body length
   >= ``min_tokens`` (default 6) are copy-paste candidates.

Language dispatch:

- Python: :mod:`ast` walk over ``FunctionDef`` whose name starts with
  ``test_`` (pytest convention) OR whose file is under ``tests/``.
- JS / TS: tree-sitter walk for ``call_expression`` targets ``describe``,
  ``it``, ``test`` (Jest / Mocha / node:test); body = the arrow / function
  argument.
- Rust: functions carrying the ``#[test]`` attribute.
- Go: functions named ``Test*`` in ``*_test.go`` files.

Unsupported languages are SKIPPED with a WARN log.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ract.parsers.tree_sitter_backend import (
    Language,
    ParseTree,
    field_named,
    iter_nodes,
    language_for,
    node_text,
    parse,
)

_LOG = logging.getLogger("ract.antilazy.test_copy_paste_polyglot")


@dataclass(frozen=True)
class TestBody:
    """One extracted test body with its normalised fingerprint.

    ``__test__ = False`` keeps pytest from trying to collect this
    dataclass on account of the ``Test`` prefix.
    """

    __test__ = False

    file: str
    language: str
    name: str
    start_row: int
    tokens: tuple[str, ...]  # normalised token stream

    def token_count(self) -> int:
        return len(self.tokens)


@dataclass(frozen=True)
class CopyPasteFinding:
    """One near-duplicate pair identified by the polyglot walk."""

    a_file: str
    a_name: str
    a_row: int
    b_file: str
    b_name: str
    b_row: int
    jaccard: float
    language: str


@dataclass(frozen=True)
class TestCopyPastePolyglotReport:
    """Aggregate polyglot copy-paste report.

    ``__test__ = False`` keeps pytest from trying to collect this
    dataclass on account of the ``Test`` prefix.
    """

    __test__ = False

    findings: tuple[CopyPasteFinding, ...] = field(default_factory=tuple)
    tests_scanned: int = 0
    skipped_files: tuple[str, ...] = field(default_factory=tuple)
    unsupported_languages: tuple[str, ...] = field(default_factory=tuple)

    def passed(self, threshold: int = 0) -> bool:
        """True when finding count is at or below ``threshold``."""
        return len(self.findings) <= threshold


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise_python_tokens(node: ast.AST) -> tuple[str, ...]:
    """Emit a stable normalised token stream for a Python subtree.

    - Identifiers -> ``ID``.
    - Constants (str/num/bool/None) -> ``LIT``.
    - Operator / control-flow node types -> the node type name.
    """
    tokens: list[str] = []
    for child in ast.walk(node):
        cname = type(child).__name__
        if cname in {"Name", "Attribute", "arg"}:
            tokens.append("ID")
        elif cname == "Constant":
            tokens.append("LIT")
        elif cname in {"FunctionDef", "AsyncFunctionDef"}:
            # Nested-function boundary: use type only, drop the name.
            tokens.append(cname)
        else:
            tokens.append(cname)
    return tuple(tokens)


def _normalise_ts_tokens(node: Any, source: bytes) -> tuple[str, ...]:
    """Tree-sitter equivalent of the Python normaliser.

    Walks the subtree and emits one token per node using rules:

    - ``identifier`` / ``property_identifier`` / ``field_identifier``
      -> ``ID``.
    - ``string`` / ``number`` / ``true`` / ``false`` / ``null`` /
      ``integer_literal`` / ``float_literal`` / ``boolean_literal``
      -> ``LIT``.
    - All other named nodes contribute their type name.
    - Anonymous punctuation nodes (``{``, ``,``, ...) are skipped.
    """
    id_types = {
        "identifier",
        "property_identifier",
        "field_identifier",
        "type_identifier",
        "shorthand_property_identifier",
        "shorthand_property_identifier_pattern",
        "scoped_identifier",
    }
    literal_types = {
        "string",
        "string_literal",
        "raw_string_literal",
        "number",
        "integer_literal",
        "float_literal",
        "boolean_literal",
        "true",
        "false",
        "null",
        "undefined",
        "nil",
        "interpreted_string_literal",
        "raw_string_literal",
        "rune_literal",
        "char_literal",
    }
    tokens: list[str] = []
    for n in iter_nodes(node):
        ntype = getattr(n, "type", "")
        if not ntype:
            continue
        # Skip anonymous (punctuation) nodes -- `is_named` is False for them.
        if not getattr(n, "is_named", True):
            continue
        if ntype in id_types:
            tokens.append("ID")
        elif ntype in literal_types:
            tokens.append("LIT")
        else:
            tokens.append(ntype)
    return tuple(tokens)


# ---------------------------------------------------------------------------
# Per-language test extractors
# ---------------------------------------------------------------------------


def _is_pytest_test_file(path: Path) -> bool:
    p = str(path).replace("\\", "/")
    if "/tests/" in p or p.startswith("tests/") or "/test/" in p:
        return True
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def _extract_python(path: Path, source: str) -> list[TestBody]:
    if not _is_pytest_test_file(path):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    bodies: list[TestBody] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("test_"):
                continue
            # Concatenate the body statement token streams.
            toks: list[str] = []
            for stmt in node.body:
                toks.extend(_normalise_python_tokens(stmt))
            bodies.append(
                TestBody(
                    file=str(path),
                    language="python",
                    name=node.name,
                    start_row=node.lineno - 1,
                    tokens=tuple(toks),
                )
            )
    return bodies


def _extract_js_ts(path: Path, tree: ParseTree) -> list[TestBody]:
    """Extract Jest/Mocha ``it(name, fn)`` / ``test(name, fn)`` bodies."""
    bodies: list[TestBody] = []
    src = tree.source_bytes
    for call in iter_nodes(tree.root_node, node_types={"call_expression"}):
        fn = field_named(call, "function")
        if fn is None:
            continue
        fn_text = node_text(fn, src)
        # Accept qualified names too (e.g. `test.only`, `it.each`, `t.test`).
        base_name = fn_text.split(".")[0].split("(")[0].strip()
        if base_name not in {"it", "test", "describe"} and base_name not in {
            "t",  # node:test convention
        }:
            continue
        args = field_named(call, "arguments")
        if args is None:
            continue
        # Find the callback argument (arrow or function expression).
        callback = None
        title = "<anonymous>"
        arg_children = [
            c for c in getattr(args, "children", ()) or ()
            if getattr(c, "is_named", True)
        ]
        for arg in arg_children:
            atype = getattr(arg, "type", "")
            if atype in {"arrow_function", "function_expression", "function"}:
                callback = arg
            elif atype in {"string", "template_string"}:
                title = node_text(arg, src).strip("'\"`")[:80]
        if callback is None:
            continue
        # Body node inside the callback.
        body = field_named(callback, "body")
        if body is None:
            body = callback
        toks = _normalise_ts_tokens(body, src)
        sp = getattr(call, "start_point", (0, 0))
        bodies.append(
            TestBody(
                file=str(path),
                language=tree.language.value,
                name=f"{base_name} {title}",
                start_row=sp[0],
                tokens=toks,
            )
        )
    return bodies


def _extract_rust(path: Path, tree: ParseTree) -> list[TestBody]:
    """Extract ``#[test]`` functions.

    Tree-sitter Python wraps Node instances on every access, so
    identity checks (``child is func``) are unreliable across
    ``iter_nodes`` and ``parent.children`` traversals. Compare by
    ``(start_byte, end_byte)`` instead.
    """
    bodies: list[TestBody] = []
    src = tree.source_bytes

    # Walk the module-level children to preserve sibling ordering
    # between attribute_item and function_item nodes. Fall back to
    # walking every function_item if the top-level scan misses one
    # (nested modules, mod blocks, cfg-gated blocks).
    def _collect_scope(scope: Any) -> None:
        prev_attr_text: str | None = None
        for child in getattr(scope, "children", ()) or ():
            ctype = getattr(child, "type", "")
            if ctype in {"attribute_item", "inner_attribute_item"}:
                prev_attr_text = node_text(child, src)
                continue
            if ctype == "function_item":
                is_test = (
                    prev_attr_text is not None
                    and "test" in prev_attr_text
                    and prev_attr_text.strip().startswith("#[")
                )
                prev_attr_text = None
                if not is_test:
                    continue
                body = field_named(child, "body")
                if body is None:
                    continue
                name_node = field_named(child, "name")
                name = node_text(name_node, src) if name_node is not None else "<anon>"
                toks = _normalise_ts_tokens(body, src)
                sp = getattr(child, "start_point", (0, 0))
                bodies.append(
                    TestBody(
                        file=str(path),
                        language="rust",
                        name=name,
                        start_row=sp[0],
                        tokens=toks,
                    )
                )
            elif ctype in {"mod_item", "impl_item", "declaration_list"}:
                # Recurse into module / impl bodies so nested #[test]
                # functions are captured too.
                inner = field_named(child, "body")
                if inner is not None:
                    _collect_scope(inner)
                else:
                    _collect_scope(child)
                # SP Q4 (module_08 v0.5.1): reset the trailing
                # attribute state after returning from a recursive
                # scope. Without this reset, an outer `#[cfg(test)]`
                # on a `mod tests { ... }` block leaks onto the next
                # sibling in the OUTER scope, mis-marking an
                # unrelated function as #[test]. Attributes attach
                # to the item they IMMEDIATELY precede; the recurse
                # already consumed that binding.
                prev_attr_text = None
            else:
                # A non-attribute, non-function element resets the
                # trailing attribute state.
                prev_attr_text = None

    _collect_scope(tree.root_node)
    return bodies


def _extract_go(path: Path, tree: ParseTree) -> list[TestBody]:
    """Extract ``func Test*(t *testing.T)`` functions in ``*_test.go``."""
    if not str(path).endswith("_test.go"):
        return []
    bodies: list[TestBody] = []
    src = tree.source_bytes
    for func in iter_nodes(tree.root_node, node_types={"function_declaration"}):
        name_node = field_named(func, "name")
        if name_node is None:
            continue
        name = node_text(name_node, src)
        if not name.startswith("Test"):
            continue
        body = field_named(func, "body")
        if body is None:
            continue
        toks = _normalise_ts_tokens(body, src)
        sp = getattr(func, "start_point", (0, 0))
        bodies.append(
            TestBody(
                file=str(path),
                language="go",
                name=name,
                start_row=sp[0],
                tokens=toks,
            )
        )
    return bodies


# ---------------------------------------------------------------------------
# Similarity + public API
# ---------------------------------------------------------------------------


def _jaccard(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Multiset Jaccard similarity in [0, 1]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    from collections import Counter

    ca = Counter(a)
    cb = Counter(b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    if union == 0:
        return 0.0
    return inter / union


def _extract_file(path: Path, source_bytes: bytes) -> tuple[Language | None, list[TestBody], bool]:
    """Return (language, bodies, grammar_available).

    ``grammar_available`` is False when the language IS supported by
    extension but the tree-sitter grammar cannot be loaded (used by
    the caller to feed the ``unsupported_languages`` report field).
    """
    lang = language_for(path)
    if lang is None:
        return None, [], False
    if lang is Language.PYTHON:
        try:
            source = source_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return lang, [], True
        return lang, _extract_python(path, source), True
    tree = parse(path, source_bytes)
    if tree is None:
        return lang, [], False
    if lang in (Language.JAVASCRIPT, Language.TYPESCRIPT, Language.TSX):
        return lang, _extract_js_ts(path, tree), True
    if lang is Language.RUST:
        return lang, _extract_rust(path, tree), True
    if lang is Language.GO:
        return lang, _extract_go(path, tree), True
    return lang, [], True


def _lang_group_key(lang_value: str) -> str:
    """Return the comparison-group key for a language value.

    SP Q6 (module_08 v0.5.1): TSX and TypeScript share the same
    grammar family (``tree-sitter-typescript``) and produce identical
    normalised token vocabularies. Grouping them separately silently
    misses a common copy-paste class -- a plain-TS unit test copied
    verbatim into a ``.tsx`` file. Fold both onto a single key so the
    Jaccard comparison sees them together. Other MVP languages keep
    their own key.
    """
    if lang_value in {"typescript", "tsx"}:
        return "typescript"
    return lang_value


def scan_test_copy_paste(
    files: Iterable[Path],
    *,
    jaccard_threshold: float = 0.85,
    min_tokens: int = 6,
) -> TestCopyPastePolyglotReport:
    """Scan test files for near-identical bodies.

    Pairs across DIFFERENT test names are reported; two tests with
    identical bodies but different names is exactly the anti-pattern.
    Same-file and cross-file pairs both count. Comparisons are
    LANGUAGE-FAMILY scoped: a Python test body is never compared with
    a Go test body (their normalised token streams live in disjoint
    vocabularies, so cross-family Jaccard would always be near-zero
    -- a correctness no-op but wasted work). TypeScript and TSX are
    treated as ONE family per SP Q6.
    """
    bodies_by_lang: dict[str, list[TestBody]] = {}
    skipped: list[str] = []
    unsupported: set[str] = set()
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError as e:
            _LOG.warning("test_copy_paste_polyglot: read failure %s: %s", path, e)
            skipped.append(str(path))
            continue
        lang, bodies, grammar_ok = _extract_file(path, raw)
        if lang is None:
            skipped.append(str(path))
            continue
        if not grammar_ok:
            unsupported.add(lang.value)
            continue
        if bodies:
            bodies_by_lang.setdefault(
                _lang_group_key(lang.value), []
            ).extend(bodies)

    tests_scanned = sum(len(v) for v in bodies_by_lang.values())
    findings: list[CopyPasteFinding] = []
    for lang_value, group in bodies_by_lang.items():
        n = len(group)
        for i in range(n):
            a = group[i]
            if a.token_count() < min_tokens:
                continue
            for j in range(i + 1, n):
                b = group[j]
                if b.token_count() < min_tokens:
                    continue
                # Skip pairs that are the SAME file+name+row (defensive; the
                # extractors do not produce dupes today but guard for the
                # copy-and-declare-twice case).
                if (
                    a.file == b.file
                    and a.name == b.name
                    and a.start_row == b.start_row
                ):
                    continue
                sim = _jaccard(a.tokens, b.tokens)
                if sim >= jaccard_threshold:
                    findings.append(
                        CopyPasteFinding(
                            a_file=a.file,
                            a_name=a.name,
                            a_row=a.start_row,
                            b_file=b.file,
                            b_name=b.name,
                            b_row=b.start_row,
                            jaccard=sim,
                            language=lang_value,
                        )
                    )
    # Stable ordering: by (a_file, a_row, b_file, b_row) then by descending
    # Jaccard so the caller sees the strongest matches first per file.
    findings.sort(
        key=lambda f: (f.a_file, f.a_row, f.b_file, f.b_row, -f.jaccard)
    )
    return TestCopyPastePolyglotReport(
        findings=tuple(findings),
        tests_scanned=tests_scanned,
        skipped_files=tuple(sorted(skipped)),
        unsupported_languages=tuple(sorted(unsupported)),
    )


def scan_test_copy_paste_in_dir(
    root: Path,
    *,
    jaccard_threshold: float = 0.85,
    min_tokens: int = 6,
    ignore_dirs: set[str] | None = None,
) -> TestCopyPastePolyglotReport:
    """Recursively scan a directory tree for polyglot copy-paste tests."""
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
    return scan_test_copy_paste(
        files,
        jaccard_threshold=jaccard_threshold,
        min_tokens=min_tokens,
    )


__all__ = [
    "CopyPasteFinding",
    "TestBody",
    "TestCopyPastePolyglotReport",
    "scan_test_copy_paste",
    "scan_test_copy_paste_in_dir",
]
