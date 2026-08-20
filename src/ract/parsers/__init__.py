"""RACT polyglot parser backends.

module_08 (v0.5.1) introduces language-dispatched AST/parse-tree
backends behind a stable :func:`~ract.parsers.tree_sitter_backend.parse`
API. Grammars are optional dependencies; when a language grammar is
unavailable the backend WARNS and callers fall back to Python-only
behaviour rather than failing loudly.
"""

from __future__ import annotations

from ract.parsers.tree_sitter_backend import (
    Language,
    ParseError,
    ParseTree,
    LANGUAGE_BY_EXTENSION,
    language_for,
    parse,
    reset_grammar_caches,
    tree_sitter_available,
)

__all__ = [
    "LANGUAGE_BY_EXTENSION",
    "Language",
    "ParseError",
    "ParseTree",
    "language_for",
    "parse",
    "reset_grammar_caches",
    "tree_sitter_available",
]
