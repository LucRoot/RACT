"""AST-deterministic chunk summarizer for the v0.5.1 retrieve primitive.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Chunk
Overflow item 2 (Summary chunking). Ships as the shipping default
for :func:`~ract.memory.chunk.format_chunk` in SUMMARY mode. The
Bonsai-council-model-based summarizer path named in the spec is
deferred to v0.6 per **ADR-0046**; the ``provider`` hook on
:func:`~ract.memory.chunk.format_chunk` is preserved unchanged as the
v0.6 slot.

## Shape

A deterministic summary body is four pieces concatenated with a single
newline separator:

1. **Signature** — the chunk's declaration (``def foo(...) -> ...``
   for Python, ``fn foo(...) -> ...`` for Rust, etc.). Already carried
   on :attr:`~ract.memory.chunk.Chunk.signature`; no parsing required
   here.
2. **Docstring first line** — first sentence-worth of the docstring /
   JSDoc / doc-comment (up to 120 chars). Language-specific extractor.
3. **Control-flow shape** — counts of ``for`` / ``while`` / ``if`` /
   ``try`` (or per-language equivalents ``except`` / ``catch`` /
   ``switch`` / ``match``). Python uses stdlib :mod:`ast` for rigor;
   other languages use bounded regex over keyword tokens (declared
   heuristic, deterministic, honest — the spec does not require
   AST-precision for the summary body, only that the summary body
   exist and describe the region).
4. **External calls** — up to ten distinct call-target names found
   in the body. Best-effort per-language extraction; provides caller-
   scan signal without full call-graph analysis.

The producer is deterministic: same input body produces the same
summary bytes. This preserves the ``chunk_id`` stability property
(``sha256(file, name, kind, locator, content_hash)``) that the
semantic index depends on — the shipped SUMMARY body is a pure
function of the source region.

## When it fires

:func:`~ract.memory.chunk.format_chunk` calls
:func:`summarize_chunk_deterministic` in the SUMMARY branch when no
``provider`` is supplied. Prior to module_05 that branch returned
``"summary unavailable"`` and set ``summary_pending=True``; the
placeholder was a self-declared gap. After module_05 the branch
returns a real summary and ``summary_pending`` becomes ``False``
whenever the summary body is non-empty.

When a ``provider`` IS supplied (v0.6 hook), provider output takes
precedence over the deterministic body; the deterministic path is
skipped entirely.

## Non-goals

- No model call, no network call, no on-disk weights. Anything
  requiring a summarizer model lands in v0.6 per ADR-0046.
- No AST-precision for non-Python languages. Python uses
  :mod:`ast` (stdlib, deterministic, correct). Other languages use
  bounded regex — miscounts on keywords inside string literals are
  documented + accepted for v0.5.1; a full tree-sitter reparse for
  a summary body is out of scope.
- No caller-set-lookup, no cross-file resolution. External calls
  are the raw call-target names as they appear in the body.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from ract.core.module_identity import _module_knot, register_module_knot

if TYPE_CHECKING:
    from ract.memory.chunk import Chunk


DOCSTRING_MAX_CHARS: int = 120
"""Cap on the first-line docstring excerpt included in the summary."""

MAX_EXTERNAL_CALLS: int = 10
"""Cap on the number of external-call names surfaced in the summary."""


# Per-language regex catalogues. Deterministic; ripgrep-style word
# boundaries. Kept small deliberately — the summary is a signal
# aggregator, not a static-analysis surface.
_PY_KEYWORD_RE: dict[str, re.Pattern[str]] = {
    "for": re.compile(r"\bfor\b"),
    "while": re.compile(r"\bwhile\b"),
    "if": re.compile(r"\bif\b"),
    "try": re.compile(r"\btry\b"),
}

_TS_KEYWORD_RE: dict[str, re.Pattern[str]] = {
    "for": re.compile(r"\bfor\b"),
    "while": re.compile(r"\bwhile\b"),
    "if": re.compile(r"\bif\b"),
    "try": re.compile(r"\btry\b"),
    "catch": re.compile(r"\bcatch\b"),
    "switch": re.compile(r"\bswitch\b"),
}

_RUST_KEYWORD_RE: dict[str, re.Pattern[str]] = {
    "for": re.compile(r"\bfor\b"),
    "while": re.compile(r"\bwhile\b"),
    "if": re.compile(r"\bif\b"),
    "loop": re.compile(r"\bloop\b"),
    "match": re.compile(r"\bmatch\b"),
}

_GO_KEYWORD_RE: dict[str, re.Pattern[str]] = {
    "for": re.compile(r"\bfor\b"),
    "if": re.compile(r"\bif\b"),
    "switch": re.compile(r"\bswitch\b"),
    "select": re.compile(r"\bselect\b"),
    "defer": re.compile(r"\bdefer\b"),
}

_LANGUAGE_KEYWORDS: dict[str, dict[str, re.Pattern[str]]] = {
    "python": _PY_KEYWORD_RE,
    "typescript": _TS_KEYWORD_RE,
    "javascript": _TS_KEYWORD_RE,
    "rust": _RUST_KEYWORD_RE,
    "go": _GO_KEYWORD_RE,
}


# Best-effort call-target regex: word chars (dot-nested attribute
# access allowed) directly followed by an opening paren. Skips
# keywords via a stopword list per language.
_CALL_TARGET_RE: re.Pattern[str] = re.compile(r"(?<![.\w])([A-Za-z_][\w.]*)\s*\(")

_PY_STOPWORDS: frozenset[str] = frozenset(
    {
        "if",
        "elif",
        "while",
        "for",
        "def",
        "class",
        "return",
        "yield",
        "raise",
        "assert",
        "print",
        "with",
        "except",
        "not",
        "and",
        "or",
        "in",
        "is",
        "lambda",
        "await",
        "async",
        "from",
        "import",
    }
)

_TS_STOPWORDS: frozenset[str] = frozenset(
    {
        "if",
        "while",
        "for",
        "switch",
        "return",
        "throw",
        "typeof",
        "instanceof",
        "new",
        "delete",
        "void",
        "await",
        "async",
        "function",
        "class",
        "extends",
        "catch",
        "yield",
    }
)

_RUST_STOPWORDS: frozenset[str] = frozenset(
    {
        "if",
        "while",
        "for",
        "match",
        "return",
        "loop",
        "fn",
        "impl",
        "let",
        "mut",
        "pub",
        "use",
        "struct",
        "enum",
        "trait",
        "async",
        "await",
    }
)

_GO_STOPWORDS: frozenset[str] = frozenset(
    {
        "if",
        "for",
        "switch",
        "select",
        "return",
        "func",
        "type",
        "struct",
        "interface",
        "package",
        "import",
        "defer",
        "go",
    }
)

_LANGUAGE_STOPWORDS: dict[str, frozenset[str]] = {
    "python": _PY_STOPWORDS,
    "typescript": _TS_STOPWORDS,
    "javascript": _TS_STOPWORDS,
    "rust": _RUST_STOPWORDS,
    "go": _GO_STOPWORDS,
}


def _first_line(text: str, cap: int = DOCSTRING_MAX_CHARS) -> str:
    """Return the first non-blank line of ``text``, trimmed to ``cap``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:cap]
    return ""


def _extract_python_docstring(body: str) -> str:
    """Return the first Python docstring line from ``body``, or empty.

    Uses stdlib :mod:`ast` to walk the top-level function / class
    definition inside ``body`` and reads
    :func:`ast.get_docstring`. Falls back to empty on
    :class:`SyntaxError` (partial-parse bodies do happen when a chunk
    body was sliced from an outer scope with balanced braces
    unmatched — the summary path is best-effort, not blocking).
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return ""
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=True)
            if doc:
                return _first_line(doc)
    # Module-level docstring.
    doc = ast.get_docstring(tree, clean=True)
    if doc:
        return _first_line(doc)
    return ""


_DOCSTRING_TRIPLE_RE: re.Pattern[str] = re.compile(
    r'("""|\'\'\')(.*?)\1',
    flags=re.DOTALL,
)

_JSDOC_RE: re.Pattern[str] = re.compile(
    r"/\*\*(.*?)\*/",
    flags=re.DOTALL,
)

_RUST_DOC_RE: re.Pattern[str] = re.compile(r"^\s*///\s?(.*)$", flags=re.MULTILINE)

_GO_DOC_RE: re.Pattern[str] = re.compile(r"^\s*//\s?(.*)$", flags=re.MULTILINE)


def _extract_docstring(body: str, language: str | None) -> str:
    """Return the first documentation line for ``body`` per ``language``.

    Python uses :mod:`ast`. Other languages use bounded regex over the
    conventional doc-comment forms:

    - TypeScript / JavaScript: leading ``/** ... */`` block.
    - Rust: leading ``/// ...`` line comments.
    - Go: leading ``// ...`` line comments immediately preceding a
      declaration.

    Best-effort; returns empty string when no docstring is present.
    """
    if language == "python":
        return _extract_python_docstring(body)
    if language in ("typescript", "javascript"):
        match = _JSDOC_RE.search(body)
        if match:
            # Strip leading ``*`` lines and pull the first non-empty line.
            raw = match.group(1)
            cleaned = "\n".join(
                line.strip().lstrip("*").strip() for line in raw.splitlines()
            )
            return _first_line(cleaned)
        return ""
    if language == "rust":
        parts: list[str] = []
        for match in _RUST_DOC_RE.finditer(body):
            parts.append(match.group(1))
            if len(parts) >= 5:
                break
        if parts:
            return _first_line("\n".join(parts))
        return ""
    if language == "go":
        parts: list[str] = []
        for match in _GO_DOC_RE.finditer(body):
            parts.append(match.group(1))
            if len(parts) >= 5:
                break
        if parts:
            return _first_line("\n".join(parts))
        return ""
    return ""


def _count_control_flow_python_ast(body: str) -> dict[str, int]:
    """Return AST-derived control-flow counts for Python ``body``.

    Falls back to the regex heuristic on :class:`SyntaxError` (partial-
    parse bodies do happen for chunk-sliced source).
    """
    counts: dict[str, int] = {"for": 0, "while": 0, "if": 0, "try": 0}
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return _count_control_flow_regex(body, "python")
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            counts["for"] += 1
        elif isinstance(node, ast.While):
            counts["while"] += 1
        elif isinstance(node, ast.If):
            counts["if"] += 1
        elif isinstance(node, ast.Try):
            counts["try"] += 1
    return counts


def _count_control_flow_regex(body: str, language: str | None) -> dict[str, int]:
    """Return regex-derived control-flow counts for non-Python languages.

    Deterministic and bounded; miscounts on keywords inside string
    literals are documented + accepted per the module docstring.
    """
    catalog = _LANGUAGE_KEYWORDS.get(language or "", _PY_KEYWORD_RE)
    return {kw: len(pattern.findall(body)) for kw, pattern in catalog.items()}


def _count_control_flow(body: str, language: str | None) -> dict[str, int]:
    """Dispatch control-flow counting per language."""
    if language == "python":
        return _count_control_flow_python_ast(body)
    return _count_control_flow_regex(body, language)


def _extract_call_targets(body: str, language: str | None) -> list[str]:
    """Return up to :data:`MAX_EXTERNAL_CALLS` distinct call-target names.

    Best-effort regex scan. Preserves first-appearance order so the
    summary is deterministic. Language stopwords filter out control-
    flow keywords that would otherwise show up as call-shaped
    (``if(...)`` in TS, ``for(...)`` in Go, etc.).
    """
    stopwords = _LANGUAGE_STOPWORDS.get(language or "python", _PY_STOPWORDS)
    seen: dict[str, None] = {}
    for match in _CALL_TARGET_RE.finditer(body):
        name = match.group(1)
        # Skip the outermost keyword like ``if`` / ``for`` / ``return``.
        head = name.split(".", 1)[0]
        if head in stopwords:
            continue
        if name in seen:
            continue
        seen[name] = None
        if len(seen) >= MAX_EXTERNAL_CALLS:
            break
    return list(seen.keys())


def summarize_chunk_deterministic(
    chunk: "Chunk",
    language: str | None = None,
) -> str:
    """Return an AST-deterministic summary body for ``chunk``.

    Body format (four lines, single newline separator):

    - Line 1: ``chunk.signature`` (or empty if signature absent).
    - Line 2: ``"doc: <first-line docstring>"`` (or omitted if
      no docstring is extractable).
    - Line 3: ``"control: for=N while=N if=N try=N"`` (or per-
      language equivalent keyword set).
    - Line 4: ``"calls: name1, name2, name3, ..."`` (up to ten;
      omitted if no calls found).

    Deterministic: same input yields the same output bytes. Safe for
    inclusion in ``content_hash`` because the summary is a pure
    function of the chunk body.

    The ``language`` parameter defaults to ``chunk.language`` when
    unspecified; callers that construct :class:`Chunk` instances
    without the language field may pass an override.
    """
    lang = language if language is not None else chunk.language
    body = chunk.body or ""
    signature = (chunk.signature or "").strip()

    lines: list[str] = []
    if signature:
        lines.append(signature)

    doc = _extract_docstring(body, lang)
    if doc:
        lines.append(f"doc: {doc}")

    counts = _count_control_flow(body, lang)
    # Keep only non-zero counts for readability; if all zero, emit
    # a single "control: none" marker so the summary is not empty on
    # straight-line bodies.
    non_zero = [f"{kw}={n}" for kw, n in counts.items() if n]
    control_line = " ".join(non_zero) if non_zero else "none"
    lines.append(f"control: {control_line}")

    calls = _extract_call_targets(body, lang)
    if calls:
        lines.append(f"calls: {', '.join(calls)}")

    return "\n".join(lines)


__all__ = [
    "DOCSTRING_MAX_CHARS",
    "MAX_EXTERNAL_CALLS",
    "summarize_chunk_deterministic",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.1
