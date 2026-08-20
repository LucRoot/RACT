"""Language-dispatched tree-sitter parse backend for polyglot ALM gates.

module_08 (v0.5.1) introduces this backend to close DeepSeek REVIEW_3
§C3 (G5/G6 currently Python-only via ``ast``). MVP languages: Python
+ JavaScript + TypeScript + Rust + Go. Additional languages plug in by
extending :data:`LANGUAGE_BY_EXTENSION` and :func:`_load_grammar`.

The backend keeps two invariants deliberately:

1. **Optional-grammar tolerance.** ``tree_sitter`` itself is already a
   hard runtime dependency of RACT (see ``pyproject.toml``; the memory-
   discipline modules use it). Per-language *grammar* packages are not
   guaranteed to be installed. When a grammar is missing the backend
   returns ``None`` from :func:`parse` and logs a WARN so callers can
   fall back to Python-only behaviour rather than fail.
2. **Byte-oriented source.** Tree-sitter node ranges are byte offsets,
   not character offsets. Every helper takes and returns
   :class:`bytes`; the caller is responsible for decoding node text.
   This matches the tree-sitter Python binding's own API surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("ract.parsers.tree_sitter")


class Language(str, Enum):
    """Enumerated MVP languages for module_08 polyglot dispatch."""

    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    RUST = "rust"
    GO = "go"


# Extension -> Language mapping. Kept small on purpose; extend by
# adding an entry here + a branch in :func:`_load_grammar`.
LANGUAGE_BY_EXTENSION: dict[str, Language] = {
    ".py": Language.PYTHON,
    ".pyi": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".mjs": Language.JAVASCRIPT,
    ".cjs": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TSX,
    ".rs": Language.RUST,
    ".go": Language.GO,
}


@dataclass(frozen=True)
class ParseError:
    """One parse-error node surfaced by tree-sitter."""

    start_row: int
    start_col: int
    end_row: int
    end_col: int
    text_preview: str = ""


@dataclass(frozen=True)
class ParseTree:
    """Result of a successful tree-sitter parse.

    ``root_node`` is the tree-sitter Node instance (raw binding
    object). ``source_bytes`` is retained so callers can slice node
    ranges without re-reading the file. ``parse_errors`` is empty for
    clean parses.
    """

    language: Language
    root_node: Any  # tree_sitter.Node — kept as Any to avoid hard import at type-check
    source_bytes: bytes
    parse_errors: tuple[ParseError, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def tree_sitter_available() -> bool:
    """Return True when the core ``tree_sitter`` package is importable."""
    try:
        import tree_sitter  # noqa: F401
    except ImportError:
        return False
    return True


# Cache of parsers keyed by Language. Tree-sitter parsers are cheap to
# construct but grammar loading is not free; caching keeps the hot path
# free of repeated import work.
_PARSER_CACHE: dict[Language, Any] = {}
_GRAMMAR_UNAVAILABLE: set[Language] = set()


def _load_grammar(language: Language) -> Any | None:
    """Load and cache a tree-sitter parser for ``language``.

    Returns ``None`` (and adds ``language`` to a "known unavailable"
    set) when the grammar package is missing or fails to construct.
    """
    if language in _PARSER_CACHE:
        return _PARSER_CACHE[language]
    if language in _GRAMMAR_UNAVAILABLE:
        return None
    try:
        import tree_sitter as ts  # type: ignore[import-not-found]
    except ImportError:
        _LOG.warning(
            "tree_sitter core package unavailable; polyglot parse for %s "
            "will fall through to no-op. Install `ract[polyglot]` to "
            "enable.",
            language.value,
        )
        _GRAMMAR_UNAVAILABLE.add(language)
        return None
    try:
        if language is Language.PYTHON:
            import tree_sitter_python as _tsp  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tsp.language())
        elif language is Language.JAVASCRIPT:
            import tree_sitter_javascript as _tsj  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tsj.language())
        elif language is Language.TYPESCRIPT:
            import tree_sitter_typescript as _tst  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tst.language_typescript())  # type: ignore[attr-defined]
        elif language is Language.TSX:
            import tree_sitter_typescript as _tstx  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tstx.language_tsx())  # type: ignore[attr-defined]
        elif language is Language.RUST:
            import tree_sitter_rust as _tsr  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tsr.language())
        elif language is Language.GO:
            import tree_sitter_go as _tsg  # type: ignore[import-not-found]

            ts_lang = ts.Language(_tsg.language())
        else:
            _LOG.warning("no grammar dispatch branch for language=%s", language)
            _GRAMMAR_UNAVAILABLE.add(language)
            return None
    except ImportError as e:
        _LOG.warning(
            "tree-sitter grammar for %s unavailable: %s. Install the "
            "matching `tree-sitter-%s` package or `ract[polyglot]`.",
            language.value,
            e,
            language.value,
        )
        _GRAMMAR_UNAVAILABLE.add(language)
        return None
    except Exception as e:  # noqa: BLE001
        _LOG.warning(
            "tree-sitter grammar for %s failed to load: %s",
            language.value,
            e,
        )
        _GRAMMAR_UNAVAILABLE.add(language)
        return None
    try:
        parser = ts.Parser(ts_lang)
    except Exception as e:  # noqa: BLE001
        _LOG.warning(
            "tree-sitter parser construction failed for %s: %s",
            language.value,
            e,
        )
        _GRAMMAR_UNAVAILABLE.add(language)
        return None
    _PARSER_CACHE[language] = parser
    return parser


def _reset_caches_for_tests() -> None:
    """Clear grammar caches. Test helper; not part of the public API."""
    _PARSER_CACHE.clear()
    _GRAMMAR_UNAVAILABLE.clear()


def reset_grammar_caches() -> None:
    """Public: clear the parser + unavailable-grammar caches.

    Long-running processes (daemons, REPLs, editor integrations) that
    install a tree-sitter grammar package MID-SESSION must call this
    after the install to invalidate the "known unavailable" marker set
    by an earlier failed load. Without it the newly-installed grammar
    stays permanently blocked for the process lifetime.

    SP Q1 (module_08 v0.5.1) closure: expose the reset that
    :func:`_reset_caches_for_tests` already implemented so operators
    are not forced to restart the process to pick up freshly-installed
    grammar packages.
    """
    _PARSER_CACHE.clear()
    _GRAMMAR_UNAVAILABLE.clear()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def language_for(file_path: Path | str) -> Language | None:
    """Return the :class:`Language` for a file's extension, or ``None``.

    Extension lookup is case-insensitive on the suffix. Files whose
    extensions are not in :data:`LANGUAGE_BY_EXTENSION` (docs, JSON,
    binary blobs) return ``None``; callers should treat that as
    "skip".
    """
    if isinstance(file_path, str):
        p = Path(file_path)
    else:
        p = file_path
    suffix = p.suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix)


def _collect_errors(node: Any, source_bytes: bytes) -> tuple[ParseError, ...]:
    """Walk the tree collecting ERROR / MISSING nodes as ParseError."""
    errors: list[ParseError] = []
    stack: list[Any] = [node]
    while stack:
        n = stack.pop()
        if getattr(n, "is_error", False) or getattr(n, "type", "") == "ERROR" or getattr(n, "is_missing", False):
            start = getattr(n, "start_point", (0, 0))
            end = getattr(n, "end_point", (0, 0))
            start_byte = getattr(n, "start_byte", 0)
            end_byte = getattr(n, "end_byte", 0)
            try:
                preview = source_bytes[start_byte:end_byte].decode(
                    "utf-8", errors="replace"
                )[:80]
            except Exception:  # noqa: BLE001
                preview = ""
            errors.append(
                ParseError(
                    start_row=start[0],
                    start_col=start[1],
                    end_row=end[0],
                    end_col=end[1],
                    text_preview=preview,
                )
            )
        for child in getattr(n, "children", ()) or ():
            stack.append(child)
    return tuple(errors)


def parse(file_path: Path | str, source: bytes) -> ParseTree | None:
    """Parse ``source`` for the language inferred from ``file_path``.

    Returns a :class:`ParseTree`, or ``None`` when the language is
    unsupported by extension OR when the tree-sitter grammar package
    is unavailable. A WARN is logged on the unavailable path so the
    operator can install the missing extra.

    ``source`` must be :class:`bytes`. Callers holding text should
    encode UTF-8 first; tree-sitter node ranges are byte offsets.
    """
    if not isinstance(source, (bytes, bytearray)):
        raise TypeError(
            f"parse(): source must be bytes, got {type(source).__name__}"
        )
    lang = language_for(file_path)
    if lang is None:
        return None
    parser = _load_grammar(lang)
    if parser is None:
        return None
    try:
        tree = parser.parse(bytes(source))
    except Exception as e:  # noqa: BLE001
        _LOG.warning(
            "tree-sitter parse failed for %s (%s): %s",
            file_path,
            lang.value,
            e,
        )
        return None
    root = tree.root_node
    errors = _collect_errors(root, bytes(source))
    return ParseTree(
        language=lang,
        root_node=root,
        source_bytes=bytes(source),
        parse_errors=errors,
    )


def parse_file(file_path: Path) -> ParseTree | None:
    """Convenience: read ``file_path`` as bytes and :func:`parse`.

    Returns ``None`` on read error or unsupported language.
    """
    try:
        raw = Path(file_path).read_bytes()
    except OSError as e:
        _LOG.warning("parse_file: read failure for %s: %s", file_path, e)
        return None
    return parse(file_path, raw)


# ---------------------------------------------------------------------------
# Tree-walk helpers used by polyglot ALM gates
# ---------------------------------------------------------------------------


# SP Q5 (module_08 v0.5.1): iter_nodes uses an explicit stack whose
# depth is bounded on pathological inputs (100k-deep left-recursive
# expressions in generated code). The default cap is generous for real
# hand-written code and prevents unbounded memory use on adversarial or
# machine-generated inputs. Override with ``max_stack_depth=None`` to
# opt out; a WARN is emitted when the cap trips and further descent
# is aborted.
DEFAULT_MAX_STACK_DEPTH = 10_000


def iter_nodes(
    node: Any,
    *,
    node_types: set[str] | None = None,
    max_stack_depth: int | None = DEFAULT_MAX_STACK_DEPTH,
) -> Any:
    """Iterate descendants of ``node``, optionally filtered by type.

    Depth-first pre-order. Yields the tree-sitter Node instances.

    ``max_stack_depth`` caps the size of the internal stack; when the
    cap trips the walk stops descending further and a WARN is logged.
    Pass ``None`` to disable the cap (SP Q5 opt-out).
    """
    stack: list[Any] = [node]
    capped = False
    while stack:
        n = stack.pop()
        if node_types is None or getattr(n, "type", "") in node_types:
            yield n
        # Push children in reverse so pop() yields them in source order.
        children = list(getattr(n, "children", ()) or ())
        for child in reversed(children):
            if max_stack_depth is not None and len(stack) >= max_stack_depth:
                if not capped:
                    _LOG.warning(
                        "iter_nodes stack cap reached (max_stack_depth=%d); "
                        "aborting further descent. Pass max_stack_depth=None "
                        "to disable the cap.",
                        max_stack_depth,
                    )
                    capped = True
                break
            stack.append(child)


def node_text(node: Any, source_bytes: bytes) -> str:
    """Return the UTF-8 decoded text spanned by ``node``."""
    start = getattr(node, "start_byte", 0)
    end = getattr(node, "end_byte", 0)
    return source_bytes[start:end].decode("utf-8", errors="replace")


def field_named(node: Any, name: str) -> Any | None:
    """Return the field-named child of ``node``, or ``None``.

    Uses ``child_by_field_name`` which the tree-sitter Python binding
    exposes on every Node.
    """
    getter = getattr(node, "child_by_field_name", None)
    if getter is None:
        return None
    try:
        return getter(name)
    except Exception:  # noqa: BLE001
        return None
